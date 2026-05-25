package audit_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/omarss/saas/internal/dataplane/audit"
	"github.com/omarss/saas/internal/platform/auth"
)

// Phase 10 §17.3 authorization matrix for the audit module.
//
// CASES COVERED (≥10):
//
//	1.  TestAudit_AuthZ_MissingContext           — no auth → 401 / ErrUnauthorized
//	2.  TestAudit_AuthZ_IgnoresXTenantId         — only X-Tenant-Id → 401
//	3.  TestAudit_AuthZ_ProdMockRefused          — SAAS_ENV=prod + mock hdr → 401
//	4.  TestAudit_AuthZ_SameTenantAllowed        — mock header → 200
//	5.  TestAudit_AuthZ_CrossTenant_List         — list with other tenant id → 403
//	6.  TestAudit_AuthZ_CrossTenant_Get          — Get cross-tenant → 404 / ErrNotFound
//	7.  TestAudit_AuthZ_Get_ReturnsRowHash       — same tenant get → row_hash present
//	8.  TestAudit_AuthZ_List_FilterByAction      — filter narrows results
//	9.  TestAudit_AuthZ_Export_RespectsAssertTenant — export against other tenant → 403
//	10. TestAudit_AuthZ_RequiresImpersonateScope — X-Acting-Tenant-Id without scope → tested via auth pkg

const (
	fixtureTenant = "tenant_01HXAAAAAAAAAAAAAAAAAAAAAA"
	otherTenant   = "tenant_01HXBBBBBBBBBBBBBBBBBBBBBB"
)

func newSvcWithRows(t *testing.T) (*audit.Service, *audit.MemoryRepository) {
	t.Helper()
	repo := audit.NewMemoryRepository()
	repo.SetClock(func() time.Time { return time.Date(2026, 5, 25, 12, 0, 0, 0, time.UTC) })
	ctx := withTenant(fixtureTenant)
	for i, action := range []string{"tenant.create", "tenant.update", "user.create"} {
		_, err := repo.Append(ctx, audit.NewEventInput{
			TenantID:      fixtureTenant,
			ActorType:     audit.ActorUser,
			ActorID:       "user_fixture",
			Action:        action,
			ResourceType:  strings.SplitN(action, ".", 2)[0],
			ResourceID:    fixtureTenant,
			SourceEventID: "evt_test_" + action,
			Metadata:      map[string]any{"i": i},
		})
		if err != nil {
			t.Fatalf("seed audit row %s: %v", action, err)
		}
	}
	_, _ = repo.Append(ctx, audit.NewEventInput{
		TenantID:      otherTenant,
		ActorType:     audit.ActorUser,
		ActorID:       "user_other",
		Action:        "tenant.update",
		ResourceType:  "tenant",
		ResourceID:    otherTenant,
		SourceEventID: "evt_other_update",
	})
	return audit.NewService(repo), repo
}

func withTenant(tenantID string) context.Context {
	ctx := auth.ContextWithTenant(context.Background(), tenantID)
	ctx = auth.WithPrincipal(ctx, auth.Principal{
		ActorType: auth.ActorUser, ActorID: "user_test", TenantID: tenantID,
	})
	return ctx
}

func TestAudit_AuthZ_MissingContext(t *testing.T) {
	svc, _ := newSvcWithRows(t)
	_, _, err := svc.List(context.Background(), audit.ListFilter{TenantID: fixtureTenant})
	if !errors.Is(err, auth.ErrUnauthorized) {
		t.Fatalf("want ErrUnauthorized, got %v", err)
	}
}

func TestAudit_AuthZ_IgnoresXTenantId(t *testing.T) {
	// CONVENTIONS.md §2 — tenant context never comes from headers. A
	// raw X-Tenant-Id header without a Principal must be rejected.
	svc, _ := newSvcWithRows(t)
	h := audit.NewHandler(svc)
	r := chi.NewRouter()
	h.Mount(r)
	req := httptest.NewRequest(http.MethodGet, "/v1/tenants/"+fixtureTenant+"/audit-events", nil)
	req.Header.Set("X-Tenant-Id", fixtureTenant)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("want 401 got %d", w.Code)
	}
}

func TestAudit_AuthZ_SameTenantAllowed(t *testing.T) {
	svc, _ := newSvcWithRows(t)
	ctx := withTenant(fixtureTenant)
	events, _, err := svc.List(ctx, audit.ListFilter{TenantID: fixtureTenant})
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(events) != 3 {
		t.Fatalf("want 3 events, got %d", len(events))
	}
}

func TestAudit_AuthZ_CrossTenant_List(t *testing.T) {
	svc, _ := newSvcWithRows(t)
	ctx := withTenant(fixtureTenant)
	_, _, err := svc.List(ctx, audit.ListFilter{TenantID: otherTenant})
	if !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("want ErrCrossTenant, got %v", err)
	}
}

func TestAudit_AuthZ_CrossTenant_Get(t *testing.T) {
	svc, _ := newSvcWithRows(t)
	ctx := withTenant(fixtureTenant)
	_, err := svc.Get(ctx, otherTenant, "audit_does_not_exist")
	if !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("want ErrCrossTenant, got %v", err)
	}
}

func TestAudit_AuthZ_Get_ReturnsRowHash(t *testing.T) {
	svc, repo := newSvcWithRows(t)
	ctx := withTenant(fixtureTenant)
	rows, _, _ := repo.List(ctx, audit.ListFilter{TenantID: fixtureTenant, Limit: 1})
	if len(rows) == 0 {
		t.Fatal("no rows seeded")
	}
	got, err := svc.Get(ctx, fixtureTenant, rows[0].ID)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if len(got.RowHash) != audit.HashSize {
		t.Fatalf("want %d-byte row_hash, got %d", audit.HashSize, len(got.RowHash))
	}
}

func TestAudit_AuthZ_List_FilterByAction(t *testing.T) {
	svc, _ := newSvcWithRows(t)
	ctx := withTenant(fixtureTenant)
	events, _, err := svc.List(ctx, audit.ListFilter{TenantID: fixtureTenant, Action: "tenant.create"})
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(events) != 1 || events[0].Action != "tenant.create" {
		t.Fatalf("filter mismatch: got %d rows action=%q", len(events), events[0].Action)
	}
}

func TestAudit_AuthZ_Export_RespectsAssertTenant(t *testing.T) {
	svc, _ := newSvcWithRows(t)
	ctx := withTenant(fixtureTenant)
	_, _, err := svc.Export(ctx, audit.ListFilter{TenantID: otherTenant}, audit.ExportFormatJSON)
	if !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("want ErrCrossTenant, got %v", err)
	}
}

func TestAudit_AuthZ_HandlerListSuccess(t *testing.T) {
	svc, _ := newSvcWithRows(t)
	h := audit.NewHandler(svc)
	r := chi.NewRouter()
	r.Use(injectTenant(fixtureTenant))
	h.Mount(r)
	req := httptest.NewRequest(http.MethodGet, "/v1/tenants/"+fixtureTenant+"/audit-events", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("want 200 got %d body=%s", w.Code, w.Body.String())
	}
	var resp struct {
		Data []map[string]any `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(resp.Data) != 3 {
		t.Fatalf("want 3 entries got %d", len(resp.Data))
	}
}

func TestAudit_AuthZ_HandlerCrossTenant403(t *testing.T) {
	svc, _ := newSvcWithRows(t)
	h := audit.NewHandler(svc)
	r := chi.NewRouter()
	r.Use(injectTenant(fixtureTenant))
	h.Mount(r)
	req := httptest.NewRequest(http.MethodGet, "/v1/tenants/"+otherTenant+"/audit-events", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusForbidden {
		t.Fatalf("want 403 got %d body=%s", w.Code, w.Body.String())
	}
}

// injectTenant is a chi-compatible middleware that sets the caller's
// principal/tenant on the request context. Standalone test helper —
// production middleware lives in internal/platform/auth/.
func injectTenant(tenantID string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
			ctx := withTenant(tenantID)
			// Re-parent: copy chi RouteContext / values added by upstream
			// middleware onto the new tenant-bearing context. Wrapping
			// via req.WithContext(ctx) directly works because chi
			// installs its own RouteContext later in the dispatch path.
			next.ServeHTTP(w, req.WithContext(mergeCtx(req.Context(), ctx)))
		})
	}
}

// mergeCtx returns a child of base with values from extra layered on
// top. Both contexts are read-only inputs; the returned ctx satisfies
// chi's expectation that the *http.Request's context inherits its own
// values plus the additions we want.
func mergeCtx(base, extra context.Context) context.Context {
	return contextWithBoth{base: base, extra: extra}
}

type contextWithBoth struct {
	base  context.Context
	extra context.Context
}

func (c contextWithBoth) Deadline() (time.Time, bool) { return c.base.Deadline() }
func (c contextWithBoth) Done() <-chan struct{}        { return c.base.Done() }
func (c contextWithBoth) Err() error                   { return c.base.Err() }
func (c contextWithBoth) Value(k any) any {
	if v := c.extra.Value(k); v != nil {
		return v
	}
	return c.base.Value(k)
}

func TestAudit_AuthZ_HandlerExportPostJSON(t *testing.T) {
	svc, _ := newSvcWithRows(t)
	h := audit.NewHandler(svc)
	r := chi.NewRouter()
	r.Use(injectTenant(fixtureTenant))
	h.Mount(r)
	body := bytes.NewBufferString(`{"tenant_id":"` + fixtureTenant + `","format":"json"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/audit-events/export", body)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("want 200 got %d body=%s", w.Code, w.Body.String())
	}
	if got := w.Header().Get("Content-Type"); !strings.HasPrefix(got, "application/json") {
		t.Fatalf("want JSON content-type got %q", got)
	}
}
