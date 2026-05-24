// Package auth provides the tenant-context primitives used everywhere a
// handler or service touches tenant-bound data. Layer 1 of the eight-layer
// tenant isolation invariant (see docs/plans/mvp/00-master.md) lives here.
//
// In Phase 2/3 the only middleware shipped is MockMiddleware, which reads a
// development-only X-Mock-Tenant-Id header. The header is rejected outright
// in production builds (build tag `prod` swaps MockMiddleware for a no-op
// passthrough — see middleware_mock.go and middleware_prod.go). Phase 5
// swaps the mock for real JWT verification via gocloak + jwx; the
// auth.TenantFromContext / auth.AssertTenant interface stays the same — only
// the middleware changes.
package auth

import (
	"context"
	"errors"
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
//
// In Phase 3 the tenant id is sourced either from the legacy tenantKey (set by
// the mock middleware before the principal-aware paths land) OR from the
// Principal in context. Both paths are honoured so Phase-2 tests pass while
// Phase-3 callers can read scopes / actor metadata.
func TenantFromContext(ctx context.Context) (string, bool) {
	if v, ok := ctx.Value(tenantKey).(string); ok && v != "" {
		return v, true
	}
	if p, ok := PrincipalFromContext(ctx); ok && p.TenantID != "" {
		return p.TenantID, true
	}
	return "", false
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
