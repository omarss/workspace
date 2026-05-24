// Package auth provides the tenant-context primitives used everywhere a
// handler or service touches tenant-bound data. Layer 1 of the eight-layer
// tenant isolation invariant (see docs/plans/mvp/00-master.md) lives here.
//
// In Phase 2 the only middleware shipped is MockMiddleware, which reads a
// development-only X-Mock-Tenant-Id header. The header is rejected outright
// in production (SAAS_ENV=prod) so a misconfigured deploy cannot accept
// caller-asserted tenants. Phase 5 swaps in real JWT verification via
// gocloak + jwx; the auth.TenantFromContext / auth.AssertTenant interface
// stays the same — only the middleware changes.
package auth

import (
	"context"
	"errors"
	"net/http"
	"os"
)

// ctxKey is an unexported type so external packages cannot inject a tenant.
// Only middleware in this package may populate the value.
type ctxKey struct{}

var tenantKey = ctxKey{}

// Sentinel errors returned to higher layers. Translated to HTTP problem
// responses by internal/platform/problem.
var (
	ErrUnauthorized = errors.New("unauthorized")
	ErrCrossTenant  = errors.New("cross-tenant access denied")
)

// TenantFromContext returns the caller's tenant_id if any. The boolean ok is
// false when the request was not authenticated (or the middleware did not run).
func TenantFromContext(ctx context.Context) (string, bool) {
	v, ok := ctx.Value(tenantKey).(string)
	return v, ok && v != ""
}

// ContextWithTenant returns a child context whose tenant is set. Exported so
// integration tests can build a context without going through middleware.
func ContextWithTenant(ctx context.Context, tenantID string) context.Context {
	return context.WithValue(ctx, tenantKey, tenantID)
}

// AssertTenant returns ErrCrossTenant when the caller's tenant differs from
// the requested resource's tenant; ErrUnauthorized when there is no tenant in
// the context at all. Every Service method that takes a tenant-bound
// resource id sourced from the URL/path/body MUST call this before reading
// or writing.
func AssertTenant(ctx context.Context, requestedTenantID string) error {
	caller, ok := TenantFromContext(ctx)
	if !ok {
		return ErrUnauthorized
	}
	if caller != requestedTenantID {
		return ErrCrossTenant
	}
	return nil
}

// MockMiddleware honors X-Mock-Tenant-Id only when SAAS_ENV != "prod". It is
// the placeholder for the JWT-based middleware that lands in Phase 5; production
// builds reject the header outright with 401 so a misconfigured deploy cannot
// accept caller-asserted tenants.
//
// The header X-Tenant-Id (without the "Mock" prefix) is intentionally ignored
// — that pattern is banned by the eight-layer isolation invariant.
func MockMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if os.Getenv("SAAS_ENV") == "prod" {
			// Refuse the mock header entirely. Header is dev-only.
			if r.Header.Get("X-Mock-Tenant-Id") != "" {
				http.Error(w, "mock middleware refused in prod", http.StatusUnauthorized)
				return
			}
			next.ServeHTTP(w, r)
			return
		}
		if tid := r.Header.Get("X-Mock-Tenant-Id"); tid != "" {
			r = r.WithContext(ContextWithTenant(r.Context(), tid))
		}
		next.ServeHTTP(w, r)
	})
}
