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
	"strconv"
	"strings"
	"time"

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
			// Phase 13 — let local dev / contract tests exercise the
			// step-up code paths without spinning up the operators realm.
			// Defaults satisfy the destructive-endpoint gate so existing
			// fixtures keep working; tests that need to provoke a 403
			// override the headers to "" (or supply an old auth_time).
			AMR:      parseMockAMR(r.Header.Get("X-Mock-Operator-Amr")),
			ACR:      headerOrDefault(r, "X-Mock-Operator-Acr", StepUpACR),
			AuthTime: mockAuthTime(r.Header.Get("X-Mock-Operator-AuthTime")),
		}
		ctx := auth.WithPrincipal(r.Context(), p)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// parseMockAMR splits the header on commas / spaces; default is "pwd otp"
// so dev fixtures behave like an MFA-enrolled operator.
func parseMockAMR(h string) []string {
	if h == "" {
		return []string{"pwd", "otp"}
	}
	fields := strings.FieldsFunc(h, func(r rune) bool { return r == ',' || r == ' ' })
	return fields
}

func headerOrDefault(r *http.Request, key, def string) string {
	if v := r.Header.Get(key); v != "" {
		return v
	}
	return def
}

// mockAuthTime accepts an RFC 3339 timestamp OR a relative duration like
// "-2m" (= 2 minutes ago). Empty defaults to "now" so green-path tests
// don't have to wire a header at all; passing "-10m" lets step-up tests
// provoke the freshness-failure branch.
func mockAuthTime(h string) time.Time {
	if h == "" {
		return time.Now().UTC()
	}
	if d, err := time.ParseDuration(h); err == nil {
		return time.Now().Add(d).UTC()
	}
	if t, err := time.Parse(time.RFC3339, h); err == nil {
		return t.UTC()
	}
	// Fallback: try a raw unix-seconds integer for parity with the JWT path.
	if i, err := strconv.ParseInt(h, 10, 64); err == nil {
		return time.Unix(i, 0).UTC()
	}
	return time.Time{}
}
