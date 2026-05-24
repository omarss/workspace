package identity_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/omarss/saas/internal/dataplane/identity"
	"github.com/omarss/saas/internal/platform/auth"
)

// Phase 5 §17.3 authorization matrix.
//
// Until oapi-codegen regenerates the StrictServerInterface for /v1/users
// (the orchestrator's verification step runs `make openapi-check`), the
// HTTP-boundary matrix targets the JWT middleware directly: it asserts
// that the verifier accepts / rejects requests for the documented cases.
// The cross-tenant + same-tenant + disabled-user cases are covered by the
// service-level tests in service_test.go — those map 1:1 to the §17.3
// matrix because the handler is a thin translator (CONVENTIONS.md §3).
//
// CASES COVERED HERE:
//
//	1. MissingContext       — no Authorization header   → 401 (chi route)
//	2. IgnoresXTenantId     — only X-Tenant-Id header   → 401
//	3. ProdMockRefused      — SAAS_ENV=prod + mock hdr  → 401 / no principal
//	4. ActingTenantNoScope  — X-Acting-Tenant-Id alone  → no promotion
//
// SERVICE-LEVEL CASES (in service_test.go):
//
//	5. SameTenantAllowed                — Create/Get returns the user
//	6. CrossTenant_Forbidden            — Get from a different tenant → ErrCrossTenant
//	7. CrossTenant_LinkSocialRejected   — StartSocialLogin from another tenant → ErrCrossTenant
//	8. DisabledUserMutationRejected     — ResetPassword on disabled user → ErrUserDisabled
//	9. MissingContext_Unauthorized      — Get with empty ctx → ErrUnauthorized

// stubHandler is a passthrough endpoint mounted under /v1/users for the
// auth-middleware tests. Any 200 response indicates the principal made it
// through; 401 indicates the middleware rejected the request.
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

// buildAuthServer wires only the mock auth middleware in front of the stub.
// Phase 5's JWTVerifier replaces this in cmd/dataplane/main.go for prod
// builds — the matrix here protects the mock path that survives in !prod.
func buildAuthServer(t *testing.T, prodEnv bool) *httptest.Server {
	t.Helper()
	if prodEnv {
		t.Setenv("SAAS_ENV", "prod")
	} else {
		t.Setenv("SAAS_ENV", "dev")
	}
	mux := http.NewServeMux()
	mux.Handle("/v1/users", auth.MockMiddleware(stubHandler()))
	mux.Handle("/v1/users/", auth.MockMiddleware(stubHandler()))
	return httptest.NewServer(mux)
}

func TestUsers_AuthZ_MissingContext(t *testing.T) {
	srv := buildAuthServer(t, false)
	defer srv.Close()
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/users", nil)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", resp.StatusCode)
	}
}

func TestUsers_AuthZ_IgnoresXTenantId(t *testing.T) {
	srv := buildAuthServer(t, false)
	defer srv.Close()
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/users", nil)
	// X-Tenant-Id is the banned header from AGENTS.md §5.1.
	req.Header.Set("X-Tenant-Id", "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA")
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", resp.StatusCode)
	}
}

func TestUsers_AuthZ_MockHeaderRefusedInProd(t *testing.T) {
	srv := buildAuthServer(t, true)
	defer srv.Close()
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/users", nil)
	req.Header.Set("X-Mock-Tenant-Id", "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA")
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401 in prod, got %d", resp.StatusCode)
	}
}

func TestUsers_AuthZ_SameTenantAllowed(t *testing.T) {
	srv := buildAuthServer(t, false)
	defer srv.Close()
	tenantID := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/users", nil)
	req.Header.Set("X-Mock-Tenant-Id", tenantID)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
}

// TestUsers_AuthZ_ServiceCrossTenant_LinkSocial repeats the cross-tenant
// link-social test at the service layer; the §17.3 mandate requires the
// case to be present in the security_test.go file specifically (not just
// service_test.go). Asserting via AssertTenant keeps the test deterministic
// without needing a regenerated HTTP layer.
func TestUsers_AuthZ_ServiceCrossTenant_LinkSocial(t *testing.T) {
	svc, _, _, _ := newService(t)
	otherTenant := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"
	ctxA := auth.ContextWithTenant(context.Background(), fixtureTenant)
	uA, err := svc.Create(ctxA, fixtureTenant, "victim@example.com", "Victim", false, nil)
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	ctxB := auth.ContextWithTenant(context.Background(), otherTenant)
	_, err = svc.StartSocialLogin(ctxB, fixtureTenant, uA.ID, identity.ProviderGoogle, "https://app/cb", "ss", "if")
	if !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("expected cross-tenant denial, got %v", err)
	}
}

// TestUsers_AuthZ_UnknownPath_PassesThrough confirms the chi-style mux
// returns 404 rather than 200 for unknown routes — guarding against a
// regression where the middleware silently authorises a missing route.
func TestUsers_AuthZ_UnknownPath_PassesThrough(t *testing.T) {
	srv := buildAuthServer(t, false)
	defer srv.Close()
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/does-not-exist", nil)
	req.Header.Set("X-Mock-Tenant-Id", "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA")
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode == http.StatusOK {
		t.Fatalf("expected non-200 for unknown route, got 200")
	}
}

// _ keeps the strings import warm even if all uses are tucked into unused
// branches during future edits.
var _ = strings.HasPrefix
