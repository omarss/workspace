//go:build !prod

// File-level build tag: this development-only middleware is excluded from
// `go build -tags prod` (the release build). Production binaries get the
// no-op passthrough from middleware_prod.go, which silently drops any
// X-Mock-* header. ADR notes: build-tag exclusion is stronger than a runtime
// SAAS_ENV check because the code physically cannot reach a prod binary.

package auth

import (
	"net/http"
	"os"
)

// MockMiddleware honors X-Mock-Tenant-Id only when SAAS_ENV != "prod" and
// only in builds without the `prod` build tag. Development convenience that
// stands in for the JWT middleware until Phase 5 lands. The mock middleware
// also populates a minimal Principal so handler code that reads
// PrincipalFromContext / RequireScope works end-to-end during local testing
// — X-Mock-Scopes is parsed via ParseScopes.
//
// The header X-Tenant-Id (without the "Mock" prefix) is intentionally ignored
// — that pattern is banned by the eight-layer isolation invariant.
func MockMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Belt-and-braces: even in a non-prod build, if someone sets
		// SAAS_ENV=prod refuse the header. This protects against accidental
		// dev binaries running with a prod env file.
		if os.Getenv("SAAS_ENV") == "prod" {
			if r.Header.Get("X-Mock-Tenant-Id") != "" {
				http.Error(w, "mock middleware refused in prod", http.StatusUnauthorized)
				return
			}
			next.ServeHTTP(w, r)
			return
		}
		tid := r.Header.Get("X-Mock-Tenant-Id")
		if tid == "" {
			next.ServeHTTP(w, r)
			return
		}
		ctx := ContextWithTenant(r.Context(), tid)
		// Best-effort principal population so Phase-3 handler code can call
		// RequireScope / PrincipalFromContext without diverging from Phase 5.
		p := Principal{
			ActorType: ActorUser,
			ActorID:   "user_mock",
			TenantID:  tid,
			Scopes:    ParseScopes(r.Header.Get("X-Mock-Scopes")),
			RequestID: r.Header.Get("X-Request-Id"),
			IPAddress: r.RemoteAddr,
			UserAgent: r.UserAgent(),
		}
		ctx = WithPrincipal(ctx, p)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
