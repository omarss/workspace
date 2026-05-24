package auth_test

import (
	"context"
	"errors"
	"testing"

	"github.com/omarss/saas/internal/platform/auth"
)

func TestPrincipalContext_Roundtrip(t *testing.T) {
	p := auth.Principal{
		ActorType: auth.ActorUser,
		ActorID:   "user_01HXYZ",
		TenantID:  "tenant_X",
		Scopes:    []string{"tenants.read", "tenants.write"},
	}
	ctx := auth.WithPrincipal(context.Background(), p)
	got, ok := auth.PrincipalFromContext(ctx)
	if !ok {
		t.Fatalf("PrincipalFromContext: missing")
	}
	if got.ActorID != p.ActorID || got.TenantID != p.TenantID {
		t.Fatalf("mismatch: %+v", got)
	}
	if got.FormatActor() != "user:user_01HXYZ" {
		t.Fatalf("FormatActor=%q", got.FormatActor())
	}
}

func TestPrincipal_HasScope(t *testing.T) {
	p := auth.Principal{Scopes: []string{"tenants.read"}}
	if !p.HasScope("tenants.read") {
		t.Fatal("expected scope present")
	}
	if p.HasScope("tenants.write") {
		t.Fatal("unexpected scope")
	}
}

func TestRequireScope_Allow(t *testing.T) {
	ctx := auth.WithPrincipal(context.Background(),
		auth.Principal{TenantID: "tenant_X", Scopes: []string{"tenants.impersonate"}})
	if err := auth.RequireScope(ctx, "tenants.impersonate"); err != nil {
		t.Fatalf("RequireScope: %v", err)
	}
}

func TestRequireScope_Deny(t *testing.T) {
	ctx := auth.WithPrincipal(context.Background(),
		auth.Principal{TenantID: "tenant_X"})
	err := auth.RequireScope(ctx, "tenants.impersonate")
	if !errors.Is(err, auth.ErrMissingScope) {
		t.Fatalf("expected ErrMissingScope, got %v", err)
	}
}

func TestRequireScope_NoPrincipal(t *testing.T) {
	err := auth.RequireScope(context.Background(), "any.scope")
	if !errors.Is(err, auth.ErrUnauthorized) {
		t.Fatalf("expected ErrUnauthorized, got %v", err)
	}
}

func TestTenantFromContext_PrefersExplicitContextValue(t *testing.T) {
	// Phase 2 mock middleware populates the legacy tenantKey; Phase 3 adds
	// principal population. TenantFromContext should resolve either source.
	ctx := auth.WithPrincipal(context.Background(),
		auth.Principal{TenantID: "tenant_FROM_PRINCIPAL"})
	tid, ok := auth.TenantFromContext(ctx)
	if !ok || tid != "tenant_FROM_PRINCIPAL" {
		t.Fatalf("expected principal tenant, got %q (ok=%v)", tid, ok)
	}
	// Legacy tenantKey wins when both are set (mock middleware sets both).
	ctx2 := auth.ContextWithTenant(ctx, "tenant_FROM_LEGACY")
	tid2, _ := auth.TenantFromContext(ctx2)
	if tid2 != "tenant_FROM_LEGACY" {
		t.Fatalf("expected legacy tenant, got %q", tid2)
	}
}

func TestActingTenantFromContext_Defaults(t *testing.T) {
	ctx := auth.WithPrincipal(context.Background(),
		auth.Principal{TenantID: "tenant_X"})
	tid, ok := auth.ActingTenantFromContext(ctx)
	if !ok || tid != "tenant_X" {
		t.Fatalf("expected tenant_X, got %q ok=%v", tid, ok)
	}
}

func TestActingTenantFromContext_Override(t *testing.T) {
	ctx := auth.WithPrincipal(context.Background(),
		auth.Principal{TenantID: "tenant_X", Scopes: []string{"tenants.impersonate"}})
	ctx = auth.WithActingTenant(ctx, "tenant_Y")
	tid, ok := auth.ActingTenantFromContext(ctx)
	if !ok || tid != "tenant_Y" {
		t.Fatalf("expected impersonation tenant_Y, got %q ok=%v", tid, ok)
	}
}

func TestParseScopes(t *testing.T) {
	tests := map[string][]string{
		"":                                   {},
		"a":                                  {"a"},
		"a b c":                              {"a", "b", "c"},
		"a, b, c":                            {"a", "b", "c"},
		"  a   b ":                           {"a", "b"},
		"tenants.read,tenants.write users.*": {"tenants.read", "tenants.write", "users.*"},
	}
	for in, want := range tests {
		got := auth.ParseScopes(in)
		if len(got) != len(want) {
			t.Errorf("ParseScopes(%q) = %v, want %v", in, got, want)
			continue
		}
		for i, w := range want {
			if got[i] != w {
				t.Errorf("ParseScopes(%q)[%d] = %q, want %q", in, i, got[i], w)
			}
		}
	}
}
