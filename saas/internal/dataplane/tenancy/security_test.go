package tenancy_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"

	httpapi "github.com/omarss/saas/internal/dataplane/httpapi" // package dataplaneapi
	"github.com/omarss/saas/internal/dataplane/tenancy"
	"github.com/omarss/saas/internal/platform/auth"
)

// strictSrv embeds the tenancy handler and stubs the healthz the strict
// interface requires.
type strictSrv struct {
	*tenancy.Handler
}

func (s *strictSrv) GetHealthz(_ context.Context, _ httpapi.GetHealthzRequestObject) (httpapi.GetHealthzResponseObject, error) {
	return httpapi.GetHealthz200JSONResponse{Status: httpapi.Ok}, nil
}

// buildServer wires the same chi router the data plane binary uses, with the
// mock auth middleware. Idempotency middleware is intentionally omitted —
// the §17.3 matrix tests authentication / authorisation only.
func buildServer(t *testing.T, prodEnv bool) (*httptest.Server, *fakeRepo) {
	t.Helper()
	if prodEnv {
		t.Setenv("SAAS_ENV", "prod")
	} else {
		t.Setenv("SAAS_ENV", "dev")
	}
	repo := newFakeRepo()
	svc := tenancy.NewService(repo, &captureEvents{})
	h := tenancy.NewHandler(svc)

	r := chi.NewRouter()
	r.Use(auth.MockMiddleware)
	httpapi.HandlerFromMux(httpapi.NewStrictHandler(&strictSrv{Handler: h}, nil), r)
	return httptest.NewServer(r), repo
}

// seedTenant inserts a tenant directly into the fake repo so authorisation
// tests have a target with a well-known id.
func seedTenant(repo *fakeRepo, id, slug string) {
	t := tenancy.Tenant{
		ID:     id,
		Slug:   slug,
		Name:   "fixture",
		Status: tenancy.StatusActive,
		RowSeq: 1,
	}
	repo.tenants[id] = t
	repo.bySlug[slug] = id
}

// TestTenants_AuthZ_SameTenantAllowed — case 1 of the §17.3 matrix.
func TestTenants_AuthZ_SameTenantAllowed(t *testing.T) {
	srv, repo := buildServer(t, false)
	defer srv.Close()
	tenantID := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	seedTenant(repo, tenantID, "acme")

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+tenantID, nil)
	req.Header.Set("X-Mock-Tenant-Id", tenantID)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	if etag := resp.Header.Get("ETag"); !strings.HasPrefix(etag, `W/"v`) {
		t.Fatalf("expected weak ETag, got %q", etag)
	}
}

// TestTenants_AuthZ_CrossTenantDenied — case 2: caller A tries to read
// tenant B and receives 403 forbidden.
func TestTenants_AuthZ_CrossTenantDenied(t *testing.T) {
	srv, repo := buildServer(t, false)
	defer srv.Close()
	a := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	b := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"
	seedTenant(repo, a, "acme")
	seedTenant(repo, b, "globex")

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+b, nil)
	req.Header.Set("X-Mock-Tenant-Id", a)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", resp.StatusCode)
	}
}

// TestTenants_AuthZ_MissingContext — case 3: no mock header → 401 unauthorized.
func TestTenants_AuthZ_MissingContext(t *testing.T) {
	srv, repo := buildServer(t, false)
	defer srv.Close()
	id := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	seedTenant(repo, id, "acme")

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+id, nil)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", resp.StatusCode)
	}
}

// TestTenants_AuthZ_MockHeaderRefusedInProd — case 4: production builds
// reject the mock header outright.
func TestTenants_AuthZ_MockHeaderRefusedInProd(t *testing.T) {
	srv, repo := buildServer(t, true)
	defer srv.Close()
	id := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	seedTenant(repo, id, "acme")

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+id, nil)
	req.Header.Set("X-Mock-Tenant-Id", id)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401 in prod, got %d", resp.StatusCode)
	}
}

// TestTenants_AuthZ_XTenantIdHeaderIgnored — case 5: the spec forbids the
// `X-Tenant-Id` header; setting it must NOT authenticate the caller.
func TestTenants_AuthZ_XTenantIdHeaderIgnored(t *testing.T) {
	srv, repo := buildServer(t, false)
	defer srv.Close()
	id := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	seedTenant(repo, id, "acme")

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+id, nil)
	// Deliberately set X-Tenant-Id (banned header). The mock middleware must
	// ignore it — only X-Mock-Tenant-Id is honoured in dev.
	req.Header.Set("X-Tenant-Id", id)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401 (header ignored), got %d", resp.StatusCode)
	}
}

// TestTenants_AuthZ_ActingTenantWithoutScope — case 6: X-Acting-Tenant-Id
// without the operator-impersonation scope must not promote the caller.
// Phase 2 does not implement scopes yet, so the only enforcement that
// matters is: setting the header alone is NOT sufficient to access another
// tenant's resource.
func TestTenants_AuthZ_ActingTenantWithoutScope(t *testing.T) {
	srv, repo := buildServer(t, false)
	defer srv.Close()
	a := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	b := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"
	seedTenant(repo, a, "acme")
	seedTenant(repo, b, "globex")

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+b, nil)
	req.Header.Set("X-Mock-Tenant-Id", a)
	req.Header.Set("X-Acting-Tenant-Id", b)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("expected 403 (acting-tenant ignored without scope), got %d", resp.StatusCode)
	}
}
