// Package operatorjwt verifies control-plane operator tokens. Phase 11
// ships the verifier shape + a non-prod mock middleware; Phase 13 wires
// the operators-realm Keycloak (deploy/keycloak/realms/operators-realm.json.tmpl)
// with MFA, step-up, and IP allowlist enforcement.
//
// Why a separate package from internal/platform/auth: the data-plane
// JWT verifier already exists with audience saas-data-<dep_id> and
// requires tenant_id. The control plane uses a distinct audience
// (saas-control), a distinct realm (`operators`), and reads
// operator_id / scopes / IP — none of which the data-plane verifier
// extracts. Splitting also makes audience mix-ups impossible: there is
// no shared verifier struct that could be misconfigured at boot.
package operatorjwt

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/lestrrat-go/httprc/v3"
	"github.com/lestrrat-go/jwx/v3/jwk"
	"github.com/lestrrat-go/jwx/v3/jwt"

	"github.com/omarss/saas/internal/platform/auth"
)

// ExpectedAudience is the mandatory aud claim for operator tokens. Any
// token whose aud is anything else (notably the per-Deployment
// saas-data-<dep_id>) is refused before any other claim is read.
const ExpectedAudience = "saas-control"

// Verifier verifies operator bearer tokens. One verifier per process;
// the JWKS cache refreshes signing keys every 15 minutes.
type Verifier struct {
	cache   *jwk.Cache
	jwksURL string
	issuer  string
}

// New constructs a Verifier and primes the JWKS cache. Caller errors at
// boot are loud — if the operators-realm IdP is unreachable the
// controlplane refuses to start rather than serve requests with an
// empty key set.
func New(ctx context.Context, jwksURL, issuer string) (*Verifier, error) {
	if jwksURL == "" || issuer == "" {
		return nil, fmt.Errorf("operatorjwt: jwksURL and issuer required")
	}
	cache, err := jwk.NewCache(ctx, httprc.NewClient())
	if err != nil {
		return nil, fmt.Errorf("operatorjwt: jwks cache: %w", err)
	}
	if err := cache.Register(ctx, jwksURL, jwk.WithMinInterval(15*time.Minute)); err != nil {
		return nil, fmt.Errorf("operatorjwt: register jwks url: %w", err)
	}
	if _, err := cache.Lookup(ctx, jwksURL); err != nil {
		return nil, fmt.Errorf("operatorjwt: prime jwks cache: %w", err)
	}
	return &Verifier{cache: cache, jwksURL: jwksURL, issuer: issuer}, nil
}

// Verify parses, validates audience + issuer, and extracts the operator
// principal. The Principal.ActorType is auth.ActorOperator; TenantID is
// left empty (operators are out-of-tenant). Phase 13 will additionally
// reject tokens with an operator_id absent from the operator table or
// with an IP outside the allowlist.
func (v *Verifier) Verify(ctx context.Context, raw string) (auth.Principal, error) {
	if v == nil || v.cache == nil {
		return auth.Principal{}, fmt.Errorf("operatorjwt: verifier not configured")
	}
	ks, err := v.cache.Lookup(ctx, v.jwksURL)
	if err != nil {
		return auth.Principal{}, fmt.Errorf("operatorjwt: jwks lookup: %w", err)
	}
	// CRITICAL: aud + iss validated before any operator_id read.
	tok, err := jwt.Parse(
		[]byte(raw),
		jwt.WithKeySet(ks),
		jwt.WithValidate(true),
		jwt.WithIssuer(v.issuer),
		jwt.WithAudience(ExpectedAudience),
	)
	if err != nil {
		return auth.Principal{}, fmt.Errorf("operatorjwt: parse token: %w", err)
	}
	var operatorID, scope, ipClaim, acr string
	_ = tok.Get("operator_id", &operatorID)
	_ = tok.Get("scope", &scope)
	_ = tok.Get("ip", &ipClaim)
	_ = tok.Get("acr", &acr)
	sub, _ := tok.Subject()
	if operatorID == "" {
		// Keycloak always emits `sub`; the operator-id mapper is best-effort.
		operatorID = sub
	}
	// AMR is an array claim per RFC 8176. jwx v3 returns it as
	// []interface{} unless a typed slice is requested.
	amr := readStringSlice(tok, "amr")
	authTime := readUnixTime(tok, "auth_time")
	// keycloak_user_id mapped from the Keycloak `sub` so downstream
	// repos can join against operator.keycloak_user_id without the
	// platform issuing a separate claim.
	return auth.Principal{
		ActorType: auth.ActorOperator,
		ActorID:   operatorID,
		Scopes:    auth.ParseScopes(scope),
		IPAddress: ipClaim,
		AMR:       amr,
		ACR:       acr,
		AuthTime:  authTime,
	}, nil
}

// readStringSlice extracts a JWT array claim as []string. jwx v3 stores
// it as []interface{} when populated by Keycloak; coercing to []string
// here keeps the principal type clean for callers.
func readStringSlice(tok jwt.Token, claim string) []string {
	var raw any
	if err := tok.Get(claim, &raw); err != nil || raw == nil {
		return nil
	}
	switch v := raw.(type) {
	case []string:
		return v
	case []any:
		out := make([]string, 0, len(v))
		for _, e := range v {
			if s, ok := e.(string); ok {
				out = append(out, s)
			}
		}
		return out
	}
	return nil
}

// readUnixTime extracts a numeric Unix-seconds claim as time.Time. Returns
// zero time when the claim is missing or malformed — callers MUST treat
// zero as "no auth_time" and reject step-up rather than calling it now.
func readUnixTime(tok jwt.Token, claim string) time.Time {
	var raw any
	if err := tok.Get(claim, &raw); err != nil || raw == nil {
		return time.Time{}
	}
	switch v := raw.(type) {
	case float64:
		return time.Unix(int64(v), 0).UTC()
	case int64:
		return time.Unix(v, 0).UTC()
	case int:
		return time.Unix(int64(v), 0).UTC()
	case time.Time:
		return v.UTC()
	}
	return time.Time{}
}

// Middleware wraps next in an operator-token verifying handler. On
// success the verified Principal is attached via auth.WithPrincipal so
// downstream handlers can call PrincipalFromContext. On failure the
// request is short-circuited with 401 and no detail (mirrors the data
// plane to avoid the JWKS-lookup-as-probing-oracle pitfall).
func (v *Verifier) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h := r.Header.Get("Authorization")
		if !strings.HasPrefix(h, "Bearer ") {
			next.ServeHTTP(w, r)
			return
		}
		raw := strings.TrimPrefix(h, "Bearer ")
		p, err := v.Verify(r.Context(), raw)
		if err != nil {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		ctx := auth.WithPrincipal(r.Context(), p)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
