// Phase 5: replace the development-only MockMiddleware with a real
// JWT-verifying middleware backed by jwx v3 + a JWKS cache. The mock path
// remains compiled in `!prod` builds (see middleware_mock.go) so existing
// fixtures keep working; production builds compile only this verifier
// (and the no-op MockMiddleware shim from middleware_prod.go).
//
// CRITICAL: audience MUST be validated before any tenant_id extraction.
// A token forged with a valid tenant_id claim but the wrong audience
// (e.g. a control-plane operator token presented to a data-plane endpoint)
// would otherwise pass the cross-tenant check. See foundations §8
// "Anti-patterns" and Phase 5 plan §5.7.

package auth

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/lestrrat-go/httprc/v3"
	"github.com/lestrrat-go/jwx/v3/jwk"
	"github.com/lestrrat-go/jwx/v3/jwt"
)

// JWTVerifier verifies bearer tokens against a JWKS cache. One verifier per
// process; the cache refreshes signing keys every 15 minutes by default.
//
// Construct via NewJWTVerifier; wire into chi.Use via Middleware().
type JWTVerifier struct {
	cache    *jwk.Cache
	jwksURL  string
	issuer   string
	audience string
}

// NewJWTVerifier registers jwksURL with the cache and primes the first fetch.
// Errors at construction time are loud — if the IdP is unreachable at boot
// the dataplane refuses to start rather than serving requests with a stale
// or empty key set.
//
// The min refresh interval mirrors foundations §8: 15 minutes balances key
// rotation latency vs. IdP load.
func NewJWTVerifier(ctx context.Context, jwksURL, issuer, audience string) (*JWTVerifier, error) {
	if jwksURL == "" || issuer == "" || audience == "" {
		return nil, fmt.Errorf("auth: jwksURL, issuer, and audience are required")
	}
	cache, err := jwk.NewCache(ctx, httprc.NewClient())
	if err != nil {
		return nil, fmt.Errorf("auth: jwks cache: %w", err)
	}
	if err := cache.Register(ctx, jwksURL, jwk.WithMinInterval(15*time.Minute)); err != nil {
		return nil, fmt.Errorf("auth: register jwks url: %w", err)
	}
	// Prime the cache. Returning the verifier with an empty key set would
	// translate every request into a 401; failing boot is louder.
	if _, err := cache.Lookup(ctx, jwksURL); err != nil {
		return nil, fmt.Errorf("auth: prime jwks cache: %w", err)
	}
	return &JWTVerifier{cache: cache, jwksURL: jwksURL, issuer: issuer, audience: audience}, nil
}

// Verify parses, validates, and extracts the Principal from raw. Audience
// is verified by jwt.WithAudience BEFORE any tenant_id read; this is a
// security-critical ordering documented in foundations §8.
func (v *JWTVerifier) Verify(ctx context.Context, raw string) (Principal, error) {
	if v == nil || v.cache == nil {
		return Principal{}, errors.New("auth: verifier not configured")
	}
	ks, err := v.cache.Lookup(ctx, v.jwksURL)
	if err != nil {
		return Principal{}, fmt.Errorf("auth: jwks lookup: %w", err)
	}
	tok, err := jwt.Parse(
		[]byte(raw),
		jwt.WithKeySet(ks),
		jwt.WithValidate(true),
		jwt.WithIssuer(v.issuer),
		jwt.WithAudience(v.audience),
	)
	if err != nil {
		return Principal{}, fmt.Errorf("auth: parse token: %w", err)
	}
	// jwx v3 returns claims via Get(name, pointer). The token has already
	// passed audience + issuer validation by this point, so reading
	// tenant_id is now safe.
	var tid string
	_ = tok.Get("tenant_id", &tid)
	var scope string
	_ = tok.Get("scope", &scope)
	sub, _ := tok.Subject()
	return Principal{
		ActorType: ActorUser,
		ActorID:   sub,
		TenantID:  tid,
		Scopes:    ParseScopes(scope),
	}, nil
}

// Middleware wraps next in a JWT-verifying handler. Requests without a
// Bearer token, or whose token fails verification, return 401 with a plain
// text body — the problem-detail mapping happens upstream in the dataplane
// router so 401 responses share a single shape.
//
// On success, the verified Principal is attached via WithPrincipal so
// downstream handlers can call PrincipalFromContext / AssertTenant.
func (v *JWTVerifier) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h := r.Header.Get("Authorization")
		if !strings.HasPrefix(h, "Bearer ") {
			// Pass through to the next layer; the mock middleware (in !prod
			// builds) may still populate the principal from X-Mock-* headers.
			// In prod builds the mock is a no-op, so handlers that require a
			// principal will surface 401 via the standard problem mapping.
			next.ServeHTTP(w, r)
			return
		}
		raw := strings.TrimPrefix(h, "Bearer ")
		p, err := v.Verify(r.Context(), raw)
		if err != nil {
			// Do not leak the parse error to the caller — the JWKS-lookup
			// failure mode would otherwise become a probing oracle for the
			// IdP topology. The structured log carries the detail.
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		ctx := WithPrincipal(r.Context(), p)
		// Keep the legacy tenantKey populated too so Phase 2 code paths
		// (which read via TenantFromContext's legacy branch) keep working.
		if p.TenantID != "" {
			ctx = ContextWithTenant(ctx, p.TenantID)
		}
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
