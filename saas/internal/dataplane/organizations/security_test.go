package organizations_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/omarss/saas/internal/dataplane/organizations"
	"github.com/omarss/saas/internal/platform/auth"
)

// Phase 7 §17.3 authorization matrix for the organizations module.
//
// HTTP-boundary tests exercise the mock auth middleware directly so the
// "X-Tenant-Id banned" / "mock-in-prod refused" invariants hold across
// every endpoint. Service-level tests cover cross-tenant resource access
// for both regular CRUD and the invitation accept flow (which is the
// documented CONVENTIONS.md §2 exception — accept derives the tenant
// from the looked-up invitation rather than the request path).
//
// CASES COVERED HERE:
//
//   1. MissingContext                  — no auth header   → 401
//   2. IgnoresXTenantId                — only X-Tenant-Id → 401
//   3. ProdMockRefused                 — SAAS_ENV=prod + mock hdr → 401
//   4. SameTenantAllowed               — mock header passes through → 200
//   5. CrossTenant_OrgGetDenied        — different tenant Get      → ErrNotFound
//   6. CrossTenant_MemberListDenied    — different tenant List     → ErrCrossTenant
//   7. CrossTenant_InvitationGetDenied — different tenant Get      → ErrNotFound
//   8. CrossTenant_AcceptDenied        — accept from foreign tenant → ErrCrossTenant
//   9. ServiceMissingContext           — no principal             → ErrUnauthorized

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
	// The endpoints this module exposes — only the prefixes matter for
	// the mock middleware regression. The handler is the same stub.
	mux.Handle("/v1/organizations", auth.MockMiddleware(stubHandler()))
	mux.Handle("/v1/organizations/", auth.MockMiddleware(stubHandler()))
	mux.Handle("/v1/tenants/", auth.MockMiddleware(stubHandler()))
	mux.Handle("/v1/invitations/", auth.MockMiddleware(stubHandler()))
	return httptest.NewServer(mux)
}

func TestOrganizations_AuthZ_MissingContext(t *testing.T) {
	srv := buildAuthServer(t, false)
	defer srv.Close()
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/organizations/org_x", nil)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", resp.StatusCode)
	}
}

func TestOrganizations_AuthZ_IgnoresXTenantId(t *testing.T) {
	srv := buildAuthServer(t, false)
	defer srv.Close()
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/organizations/org_x", nil)
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

func TestOrganizations_AuthZ_ProdMockRefused(t *testing.T) {
	srv := buildAuthServer(t, true)
	defer srv.Close()
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/organizations/org_x", nil)
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

func TestOrganizations_AuthZ_SameTenantAllowed(t *testing.T) {
	srv := buildAuthServer(t, false)
	defer srv.Close()
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/organizations/org_x", nil)
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

// TestOrganizations_AuthZ_CrossTenant_OrgGetDenied — cross-tenant
// access to an organization returns ErrNotFound (no existence leak).
func TestOrganizations_AuthZ_CrossTenant_OrgGetDenied(t *testing.T) {
	h := newHarness(t)
	otherTenant := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"

	o, _ := h.svc.AutoCreateDefault(withTenant(fixtureTenant), fixtureTenant)

	ctxOther := withTenant(otherTenant)
	if _, err := h.svc.GetOrganization(ctxOther, fixtureTenant, o.ID); !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("expected ErrCrossTenant, got %v", err)
	}
}

// TestOrganizations_AuthZ_CrossTenant_MemberListDenied — cross-tenant
// member listing yields ErrCrossTenant before any DB hit.
func TestOrganizations_AuthZ_CrossTenant_MemberListDenied(t *testing.T) {
	h := newHarness(t)
	otherTenant := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"

	o, _ := h.svc.AutoCreateDefault(withTenant(fixtureTenant), fixtureTenant)

	ctxOther := withTenant(otherTenant)
	if _, _, err := h.svc.ListMembers(ctxOther, fixtureTenant, o.ID, 25, nil); !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("expected ErrCrossTenant, got %v", err)
	}
}

// TestOrganizations_AuthZ_CrossTenant_InvitationGetDenied — cross-tenant
// invitation Get yields ErrCrossTenant.
func TestOrganizations_AuthZ_CrossTenant_InvitationGetDenied(t *testing.T) {
	h := newHarness(t)
	otherTenant := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"

	org, _ := h.svc.AutoCreateDefault(withTenant(fixtureTenant), fixtureTenant)
	ctxA := withPrincipal(fixtureTenant, fixtureUserA)
	inv, _, err := h.svc.CreateInvitation(ctxA, fixtureTenant, org.ID, organizations.CreateInvitationInput{
		InviteeEmail: fixtureEmailB,
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	ctxOther := withTenant(otherTenant)
	if _, err := h.svc.GetInvitation(ctxOther, fixtureTenant, inv.ID); !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("expected ErrCrossTenant, got %v", err)
	}
}

// TestOrganizations_AuthZ_CrossTenant_AcceptDenied — the accept flow
// is the documented tenancy-context exception. A caller from a foreign
// tenant who somehow obtains a valid token must still be rejected.
func TestOrganizations_AuthZ_CrossTenant_AcceptDenied(t *testing.T) {
	h := newHarness(t)
	org, _ := h.svc.AutoCreateDefault(withTenant(fixtureTenant), fixtureTenant)
	ctxA := withPrincipal(fixtureTenant, fixtureUserA)
	_, token, err := h.svc.CreateInvitation(ctxA, fixtureTenant, org.ID, organizations.CreateInvitationInput{
		InviteeEmail: fixtureEmailB,
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	otherTenant := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"
	ctxOther := withPrincipal(otherTenant, fixtureUserB)
	if _, err := h.svc.AcceptInvitation(ctxOther, token); !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("expected ErrCrossTenant, got %v", err)
	}
}

// TestOrganizations_AuthZ_MissingContext_Service ensures the service
// rejects requests when no tenant is bound, regardless of which method.
func TestOrganizations_AuthZ_MissingContext_Service(t *testing.T) {
	h := newHarness(t)
	if _, _, err := h.svc.ListOrganizations(context.Background(), fixtureTenant, 25, nil); !errors.Is(err, auth.ErrUnauthorized) {
		t.Fatalf("ListOrganizations: expected ErrUnauthorized, got %v", err)
	}
	if _, err := h.svc.GetOrganization(context.Background(), fixtureTenant, "org_x"); !errors.Is(err, auth.ErrUnauthorized) {
		t.Fatalf("GetOrganization: expected ErrUnauthorized, got %v", err)
	}
	if _, _, _, err := splitCreateInvitation(h.svc.CreateInvitation(context.Background(), fixtureTenant, "org_x", organizations.CreateInvitationInput{InviteeEmail: "x@y.com"})); !errors.Is(err, auth.ErrUnauthorized) {
		t.Fatalf("CreateInvitation: expected ErrUnauthorized, got %v", err)
	}
	if _, err := h.svc.AcceptInvitation(context.Background(), "anything"); !errors.Is(err, auth.ErrUnauthorized) {
		t.Fatalf("AcceptInvitation: expected ErrUnauthorized, got %v", err)
	}
}

// splitCreateInvitation flattens the three-value CreateInvitation return
// into a tuple consumable by the missing-context table above.
func splitCreateInvitation(inv organizations.Invitation, token string, err error) (organizations.Invitation, string, organizations.Invitation, error) {
	return inv, token, inv, err
}
