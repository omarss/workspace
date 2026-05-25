package authorization_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/omarss/saas/internal/dataplane/authorization"
	"github.com/omarss/saas/internal/platform/auth"
)

// Phase 8 §17.3 authorization matrix for the authorization module.
//
// HTTP-boundary tests exercise the mock auth middleware directly so the
// "X-Tenant-Id banned" / "mock-in-prod refused" invariants hold across
// every endpoint. Service-level tests cover cross-tenant attempts on
// the resources the module owns (roles, member-role assignments,
// check / batch-check).
//
// CASES COVERED HERE (each maps to a row in CONVENTIONS.md §5):
//
//   1. MissingContext                  — no auth header   → 401
//   2. IgnoresXTenantId                — only X-Tenant-Id → 401
//   3. ProdMockRefused                 — SAAS_ENV=prod + mock hdr → 401
//   4. SameTenantAllowed               — mock header passes through → 200
//   5. CrossTenant_RoleCreate_Denied   — role create in other tenant → ErrCrossTenant
//   6. CrossTenant_AssignDenied        — assign foreign-tenant member → ErrCrossTenantMember
//   7. CrossTenant_CheckDenied         — Check with member from another tenant → ErrCrossTenantMember
//   8. Wildcard_Domain_Rejected        — service refuses dom="*"
//   9. Denied_Check_EmitsAuditEvent    — denial publishes authorization.denied

func stubHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, ok := auth.PrincipalFromContext(r.Context())
		if !ok {
			http.Error(w, "no principal", http.StatusUnauthorized)
			return
		}
		w.WriteHeader(http.StatusOK)
	})
}

func buildAuthServer(t *testing.T, prodEnv bool) *httptest.Server {
	t.Helper()
	if prodEnv {
		t.Setenv("SAAS_ENV", "prod")
	} else {
		t.Setenv("SAAS_ENV", "dev")
	}
	mux := http.NewServeMux()
	mux.Handle("/v1/tenants/", auth.MockMiddleware(stubHandler()))
	mux.Handle("/v1/roles/", auth.MockMiddleware(stubHandler()))
	mux.Handle("/v1/permissions", auth.MockMiddleware(stubHandler()))
	mux.Handle("/v1/members/", auth.MockMiddleware(stubHandler()))
	mux.Handle("/v1/authorization/", auth.MockMiddleware(stubHandler()))
	return httptest.NewServer(mux)
}

func TestAuthorization_AuthZ_MissingContext(t *testing.T) {
	srv := buildAuthServer(t, false)
	defer srv.Close()
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+fixtureTenant+"/roles", nil)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", resp.StatusCode)
	}
}

func TestAuthorization_AuthZ_IgnoresXTenantId(t *testing.T) {
	srv := buildAuthServer(t, false)
	defer srv.Close()
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/permissions", nil)
	// The platform's documented invariant: X-Tenant-Id is BANNED as a
	// tenant source. The middleware ignores it entirely; no principal
	// is populated; the request returns 401.
	req.Header.Set("X-Tenant-Id", fixtureTenant)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", resp.StatusCode)
	}
}

func TestAuthorization_AuthZ_ProdMockRefused(t *testing.T) {
	srv := buildAuthServer(t, true)
	defer srv.Close()
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/permissions", nil)
	req.Header.Set("X-Mock-Tenant-Id", fixtureTenant)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401 in prod, got %d", resp.StatusCode)
	}
}

func TestAuthorization_AuthZ_SameTenantAllowed(t *testing.T) {
	srv := buildAuthServer(t, false)
	defer srv.Close()
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/permissions", nil)
	req.Header.Set("X-Mock-Tenant-Id", fixtureTenant)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
}

// TestAuthorization_AuthZ_CrossTenant_RoleCreate_Denied — calling
// CreateRole with a target tenant different from the caller's tenant
// fails the AssertTenant guard before any DB hit.
func TestAuthorization_AuthZ_CrossTenant_RoleCreate_Denied(t *testing.T) {
	h := newHarness(t)
	ctxA := withTenant(fixtureTenant)
	if _, err := h.svc.CreateRole(ctxA, fixtureTenantB, authorization.CreateRoleInput{Name: "x"}); !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("expected ErrCrossTenant, got %v", err)
	}
}

// TestAuthorization_AuthZ_CrossTenant_AssignDenied — the caller is in
// tenant_A; the targeted member belongs to tenant_B. ErrCrossTenantMember.
func TestAuthorization_AuthZ_CrossTenant_AssignDenied(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant(fixtureTenant)
	role, err := h.svc.CreateRole(ctx, fixtureTenant, authorization.CreateRoleInput{Name: "x"})
	if err != nil {
		t.Fatalf("CreateRole: %v", err)
	}
	if _, err := h.svc.AssignMemberRole(ctx, fixtureTenant, fixtureMemberB, role.ID); !errors.Is(err, authorization.ErrCrossTenantMember) {
		t.Fatalf("expected ErrCrossTenantMember, got %v", err)
	}
}

// TestAuthorization_AuthZ_CrossTenant_CheckDenied — Check refuses when
// the member belongs to a tenant other than the one in the request.
func TestAuthorization_AuthZ_CrossTenant_CheckDenied(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant(fixtureTenant)
	_, err := h.svc.Check(ctx, fixtureTenant, fixtureMemberB, "tenant.read")
	if !errors.Is(err, authorization.ErrCrossTenantMember) {
		t.Fatalf("expected ErrCrossTenantMember, got %v", err)
	}
}

// TestAuthorization_AuthZ_WildcardDomain_Rejected — wildcard tenant
// refused by the service guard and the enforcer guard.
func TestAuthorization_AuthZ_WildcardDomain_Rejected(t *testing.T) {
	h := newHarness(t)
	// Service-layer guard via the role name validator.
	ctx := withTenant(fixtureTenant)
	if _, err := h.svc.CreateRole(ctx, fixtureTenant, authorization.CreateRoleInput{Name: "*"}); err == nil {
		t.Fatalf("expected error for role name *, got nil")
	}
	// Policy-layer guard via the enforcer.
	if err := h.enforcer.AddRolePolicy(ctx, "role_x", "*", "tenant", "read"); !errors.Is(err, authorization.ErrWildcardDomain) {
		t.Fatalf("expected ErrWildcardDomain, got %v", err)
	}
}

// TestAuthorization_AuthZ_Denied_EmitsAuditEvent — every denied Check
// publishes an authorization.denied outbox event.
func TestAuthorization_AuthZ_Denied_EmitsAuditEvent(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant(fixtureTenant)
	resp, err := h.svc.Check(ctx, fixtureTenant, fixtureMemberA, "tenant.read")
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	if resp.Allowed {
		t.Fatalf("expected denied (no policies seeded), got allowed=%v", resp)
	}
	if h.events.countOfType("authorization.denied") != 1 {
		t.Fatalf("expected 1 authorization.denied event, got %d", h.events.countOfType("authorization.denied"))
	}
	last := h.events.events[len(h.events.events)-1]
	if last.Payload["permission"] != "tenant.read" {
		t.Fatalf("expected permission in payload, got %+v", last.Payload)
	}
}

// TestAuthorization_AuthZ_RequiresImpersonateScope — the impersonation
// flow lives in the auth middleware (Phase 5); authorization's
// service simply consults the caller's tenant from context. We exercise
// the negative path: a principal with TenantID="" is treated as missing.
func TestAuthorization_AuthZ_RequiresImpersonateScope(t *testing.T) {
	h := newHarness(t)
	ctx := auth.WithPrincipal(context.Background(), auth.Principal{
		ActorType: auth.ActorOperator,
		ActorID:   "op_test",
		// TenantID intentionally empty — operator without impersonation
		// must NOT see tenant-bound resources.
	})
	if _, err := h.svc.CreateRole(ctx, fixtureTenant, authorization.CreateRoleInput{Name: "x"}); !errors.Is(err, auth.ErrUnauthorized) {
		t.Fatalf("expected ErrUnauthorized for operator without tenant, got %v", err)
	}
}
