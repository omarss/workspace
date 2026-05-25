package apikeys

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/problem"
)

// Middleware is the bearer-token verifier that sits BEFORE the JWT
// middleware in the auth chain. If the Authorization header carries a
// bearer that starts with "live_" or "test_" the middleware verifies
// the token against the api_key table and sets a Principal; otherwise
// it passes through to the next middleware untouched.
//
// Failure modes (per ADR 008 + §17.3 matrix):
//
//   - missing/malformed bearer prefix     → pass through (JWT path handles it)
//   - well-formed but no matching row     → 401 unauthorized
//   - argon verify fail                   → 401 unauthorized
//   - revoked                             → 401 api-key-revoked
//   - expired or post-grace               → 401 api-key-expired
//   - IP outside allowlist                → 403 ip-not-allowlisted
//   - rate limit                          → 429 rate-limited + RateLimit-* headers
//
// The verifier records the matched api_key id in the usage buffer
// before serving — fire-and-forget, the handler does not block on
// last_used_at persistence.
func Middleware(v *Verifier) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			h := r.Header.Get("Authorization")
			if !HasBearerPrefix(h) {
				// Not an API key bearer (or no bearer at all). Pass through.
				next.ServeHTTP(w, r)
				return
			}
			bearer := ExtractBearer(h)
			if bearer == "" {
				writeMiddlewareProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized, "Missing bearer token.")
				return
			}
			res, err := v.Verify(r.Context(), bearer, r.RemoteAddr)
			if err != nil {
				switch {
				case IsRateLimited(err):
					writeRateLimited(w, r, res.RateLimitInfo)
				case errors.Is(err, auth.ErrKeyRevoked):
					writeMiddlewareProblem(w, r, http.StatusUnauthorized, problem.TypeKeyRevoked, "API key revoked.")
				case errors.Is(err, auth.ErrKeyExpired):
					writeMiddlewareProblem(w, r, http.StatusUnauthorized, problem.TypeKeyExpired, "API key expired.")
				case errors.Is(err, auth.ErrIPNotAllowed):
					writeMiddlewareProblem(w, r, http.StatusForbidden, problem.TypeIPNotAllowed, "Source IP not in allowlist.")
				default:
					writeMiddlewareProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized, "Missing or invalid bearer token / API key.")
				}
				return
			}
			// Successful verification — write rate-limit hint headers
			// when the limiter ran.
			if res.RateLimitInfo != nil {
				w.Header().Set("RateLimit-Limit", strconv.Itoa(res.RateLimitInfo.Limit))
				w.Header().Set("RateLimit-Remaining", strconv.Itoa(res.RateLimitInfo.Remaining))
			}
			ctx := auth.WithPrincipal(r.Context(), res.Principal)
			ctx = auth.ContextWithTenant(ctx, res.Principal.TenantID)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

func writeMiddlewareProblem(w http.ResponseWriter, r *http.Request, status int, typeURI, title string) {
	p := problem.Problem{
		Type:     typeURI,
		Title:    title,
		Status:   status,
		Instance: r.URL.Path,
	}
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(p)
}

func writeRateLimited(w http.ResponseWriter, r *http.Request, info *RateLimitInfo) {
	if info != nil {
		w.Header().Set("RateLimit-Limit", strconv.Itoa(info.Limit))
		w.Header().Set("RateLimit-Remaining", "0")
		w.Header().Set("Retry-After", strconv.Itoa(info.RetryAfter))
	}
	p := problem.Problem{
		Type:     problem.TypeRateLimited,
		Title:    "Rate limit exceeded.",
		Status:   http.StatusTooManyRequests,
		Instance: r.URL.Path,
	}
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(http.StatusTooManyRequests)
	_ = json.NewEncoder(w).Encode(p)
}

// PrincipalFromRequest exposes a helper for tests + integrations that
// need a quick principal read after the verifier sets context.
func PrincipalFromRequest(r *http.Request) (auth.Principal, bool) {
	return auth.PrincipalFromContext(r.Context())
}

// EnsureContextHasTenant is a defensive helper exposed for tests that
// stitch the verifier into a custom chain. Returns the request context
// unchanged when a tenant is already bound; otherwise returns ctx as
// is (no-op).
func EnsureContextHasTenant(ctx context.Context) context.Context { return ctx }
