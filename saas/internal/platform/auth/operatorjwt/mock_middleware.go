//go:build !prod

// File-level build tag: this development-only middleware is excluded
// from `go build -tags prod`. Production binaries get the no-op
// passthrough from mock_middleware_prod.go.
//
// Mirrors the data-plane pattern: a header-driven middleware lets
// local dev + integration tests assert behaviour against a fixed
// operator principal without spinning up Keycloak. The header names
// (X-Mock-Operator-Id, X-Mock-Operator-Scopes) are distinct from the
// data-plane X-Mock-Tenant-Id so a misrouted request to the wrong
// plane has no effect.

package operatorjwt

import (
	"net/http"
	"os"

	"github.com/omarss/saas/internal/platform/auth"
)

// MockMiddleware honours X-Mock-Operator-Id only when SAAS_ENV != "prod"
// AND only in builds without the `prod` tag. Stands in for the real
// operators-realm verifier until Phase 13 wires Keycloak.
//
// The X-Tenant-Id header (no Mock prefix) is intentionally ignored —
// the eight-layer isolation invariant forbids header-driven tenant
// selection (AGENTS.md §18.1).
func MockMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if os.Getenv("SAAS_ENV") == "prod" {
			if r.Header.Get("X-Mock-Operator-Id") != "" {
				http.Error(w, "operator mock middleware refused in prod", http.StatusUnauthorized)
				return
			}
			next.ServeHTTP(w, r)
			return
		}
		opID := r.Header.Get("X-Mock-Operator-Id")
		if opID == "" {
			next.ServeHTTP(w, r)
			return
		}
		p := auth.Principal{
			ActorType: auth.ActorOperator,
			ActorID:   opID,
			Scopes:    auth.ParseScopes(r.Header.Get("X-Mock-Operator-Scopes")),
			IPAddress: r.RemoteAddr,
			UserAgent: r.UserAgent(),
			RequestID: r.Header.Get("X-Request-Id"),
		}
		ctx := auth.WithPrincipal(r.Context(), p)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
