package auth_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/omarss/saas/internal/platform/auth"
)

func TestAssertTenant_SameTenant(t *testing.T) {
	ctx := auth.ContextWithTenant(context.Background(), "tenant_A")
	if err := auth.AssertTenant(ctx, "tenant_A"); err != nil {
		t.Fatalf("expected nil, got %v", err)
	}
}

func TestAssertTenant_CrossTenant(t *testing.T) {
	ctx := auth.ContextWithTenant(context.Background(), "tenant_A")
	err := auth.AssertTenant(ctx, "tenant_B")
	if !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("expected ErrCrossTenant, got %v", err)
	}
}

func TestAssertTenant_MissingContext(t *testing.T) {
	err := auth.AssertTenant(context.Background(), "tenant_A")
	if !errors.Is(err, auth.ErrUnauthorized) {
		t.Fatalf("expected ErrUnauthorized, got %v", err)
	}
}

func TestMockMiddleware_HonoursHeaderInDev(t *testing.T) {
	t.Setenv("SAAS_ENV", "dev")
	var seen string
	h := auth.MockMiddleware(http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) {
		seen, _ = auth.TenantFromContext(r.Context())
	}))
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("X-Mock-Tenant-Id", "tenant_X")
	h.ServeHTTP(httptest.NewRecorder(), req)
	if seen != "tenant_X" {
		t.Fatalf("expected tenant_X, got %q", seen)
	}
}

func TestMockMiddleware_RefusesHeaderInProd(t *testing.T) {
	t.Setenv("SAAS_ENV", "prod")
	h := auth.MockMiddleware(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		t.Fatal("downstream must not run")
		w.WriteHeader(http.StatusOK)
	}))
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("X-Mock-Tenant-Id", "tenant_X")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
}

func TestMockMiddleware_IgnoresXTenantIdHeader(t *testing.T) {
	t.Setenv("SAAS_ENV", "dev")
	var seen string
	var found bool
	h := auth.MockMiddleware(http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) {
		seen, found = auth.TenantFromContext(r.Context())
	}))
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	// X-Tenant-Id (without "Mock") is forbidden by the §18.1 invariant.
	req.Header.Set("X-Tenant-Id", "tenant_FAKE")
	h.ServeHTTP(httptest.NewRecorder(), req)
	if found || seen != "" {
		t.Fatalf("X-Tenant-Id must be ignored, got %q (found=%v)", seen, found)
	}
}
