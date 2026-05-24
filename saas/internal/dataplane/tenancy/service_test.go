package tenancy_test

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/omarss/saas/internal/dataplane/tenancy"
	"github.com/omarss/saas/internal/platform/auth"
)

// fakeRepo is an in-memory Repository used by service unit tests. It does not
// emulate RLS — the service-layer tests are about orchestration, not isolation.
// RLS behaviour is covered by repo_pgx_test.go.
type fakeRepo struct {
	tenants   map[string]tenancy.Tenant
	bySlug    map[string]string
	createErr error
	updateErr error
}

func newFakeRepo() *fakeRepo {
	return &fakeRepo{tenants: map[string]tenancy.Tenant{}, bySlug: map[string]string{}}
}

func (r *fakeRepo) Create(_ context.Context, t tenancy.Tenant) (tenancy.Tenant, error) {
	if r.createErr != nil {
		return tenancy.Tenant{}, r.createErr
	}
	if _, ok := r.bySlug[t.Slug]; ok {
		return tenancy.Tenant{}, tenancy.ErrSlugTaken
	}
	r.tenants[t.ID] = t
	r.bySlug[t.Slug] = t.ID
	return t, nil
}

func (r *fakeRepo) Get(_ context.Context, id string) (tenancy.Tenant, error) {
	t, ok := r.tenants[id]
	if !ok || t.DeletedAt != nil {
		return tenancy.Tenant{}, tenancy.ErrNotFound
	}
	return t, nil
}

func (r *fakeRepo) GetBySlug(_ context.Context, slug string) (tenancy.Tenant, error) {
	id, ok := r.bySlug[slug]
	if !ok {
		return tenancy.Tenant{}, tenancy.ErrNotFound
	}
	return r.tenants[id], nil
}

func (r *fakeRepo) List(_ context.Context, _ int, _ *tenancy.ListCursor) ([]tenancy.Tenant, bool, error) {
	out := make([]tenancy.Tenant, 0, len(r.tenants))
	for _, t := range r.tenants {
		out = append(out, t)
	}
	return out, false, nil
}

func (r *fakeRepo) Update(_ context.Context, id string, expected int64, patch tenancy.UpdatePatch) (tenancy.Tenant, error) {
	if r.updateErr != nil {
		return tenancy.Tenant{}, r.updateErr
	}
	t, ok := r.tenants[id]
	if !ok || t.DeletedAt != nil {
		return tenancy.Tenant{}, tenancy.ErrNotFound
	}
	if t.RowSeq != expected {
		return tenancy.Tenant{}, tenancy.ErrETagMismatch
	}
	if patch.Name != nil {
		t.Name = *patch.Name
	}
	if patch.Status != nil {
		t.Status = *patch.Status
	}
	if patch.PatchMetadata {
		t.Metadata = patch.Metadata
	}
	t.RowSeq++
	t.UpdatedAt = time.Now().UTC()
	r.tenants[id] = t
	return t, nil
}

func (r *fakeRepo) SoftDelete(_ context.Context, id string, expected int64) (tenancy.Tenant, error) {
	t, ok := r.tenants[id]
	if !ok || t.DeletedAt != nil {
		return tenancy.Tenant{}, tenancy.ErrNotFound
	}
	if t.RowSeq != expected {
		return tenancy.Tenant{}, tenancy.ErrETagMismatch
	}
	now := time.Now().UTC()
	t.Status = tenancy.StatusDeleted
	t.DeletedAt = &now
	t.RowSeq++
	r.tenants[id] = t
	return t, nil
}

// captureEvents collects publish calls for assertion.
type captureEvents struct {
	events   []capturedEvent
	failNext bool
}

type capturedEvent struct {
	eventType string
	tenantID  string
}

func (c *captureEvents) Publish(_ context.Context, eventType, tenantID string, _ map[string]any) error {
	if c.failNext {
		c.failNext = false
		return errors.New("publish failed")
	}
	c.events = append(c.events, capturedEvent{eventType, tenantID})
	return nil
}

func TestService_Create_HappyPath(t *testing.T) {
	repo := newFakeRepo()
	pub := &captureEvents{}
	svc := tenancy.NewService(repo, pub)

	got, err := svc.Create(context.Background(), "acme", "Acme Inc", map[string]string{"region": "ksa"})
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	if !strings.HasPrefix(got.ID, "tenant_") || len(got.ID) != len("tenant_")+26 {
		t.Fatalf("expected tenant_<ulid>, got %q", got.ID)
	}
	if got.Status != tenancy.StatusActive {
		t.Fatalf("expected active, got %q", got.Status)
	}
	if got.RowSeq != 1 {
		t.Fatalf("expected row_seq=1, got %d", got.RowSeq)
	}
	if len(pub.events) != 1 || pub.events[0].eventType != "tenant.created" {
		t.Fatalf("expected tenant.created event, got %#v", pub.events)
	}
}

func TestService_Create_DuplicateSlug(t *testing.T) {
	repo := newFakeRepo()
	svc := tenancy.NewService(repo, &captureEvents{})
	if _, err := svc.Create(context.Background(), "acme", "Acme", nil); err != nil {
		t.Fatalf("first Create: %v", err)
	}
	_, err := svc.Create(context.Background(), "acme", "Acme Two", nil)
	if !errors.Is(err, tenancy.ErrSlugTaken) {
		t.Fatalf("expected ErrSlugTaken, got %v", err)
	}
}

func TestService_Create_InvalidSlug(t *testing.T) {
	svc := tenancy.NewService(newFakeRepo(), &captureEvents{})
	cases := []string{"", "a", "-acme", "Acme", "acme-", "acm_e", strings.Repeat("a", 40)}
	for _, slug := range cases {
		if _, err := svc.Create(context.Background(), slug, "n", nil); !errors.Is(err, tenancy.ErrInvalidInput) {
			t.Errorf("slug %q: expected ErrInvalidInput, got %v", slug, err)
		}
	}
}

func TestService_Create_PublishErrorDoesNotBlock(t *testing.T) {
	repo := newFakeRepo()
	pub := &captureEvents{failNext: true}
	svc := tenancy.NewService(repo, pub)
	got, err := svc.Create(context.Background(), "acme", "Acme", nil)
	if err != nil {
		t.Fatalf("Create should not fail on publish error, got %v", err)
	}
	if _, ok := repo.tenants[got.ID]; !ok {
		t.Fatalf("tenant should still be persisted")
	}
}

func TestService_Get_SameTenant(t *testing.T) {
	repo := newFakeRepo()
	svc := tenancy.NewService(repo, &captureEvents{})
	created, _ := svc.Create(context.Background(), "acme", "Acme", nil)
	ctx := auth.ContextWithTenant(context.Background(), created.ID)
	got, err := svc.Get(ctx, created.ID)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if got.ID != created.ID {
		t.Fatalf("ID mismatch")
	}
}

func TestService_Get_CrossTenant_Forbidden(t *testing.T) {
	repo := newFakeRepo()
	svc := tenancy.NewService(repo, &captureEvents{})
	other, _ := svc.Create(context.Background(), "acme", "Acme", nil)
	ctx := auth.ContextWithTenant(context.Background(), "tenant_OTHER")
	_, err := svc.Get(ctx, other.ID)
	if !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("expected ErrCrossTenant, got %v", err)
	}
}

func TestService_Get_NoTenantContext_Unauthorized(t *testing.T) {
	repo := newFakeRepo()
	svc := tenancy.NewService(repo, &captureEvents{})
	t1, _ := svc.Create(context.Background(), "acme", "Acme", nil)
	_, err := svc.Get(context.Background(), t1.ID)
	if !errors.Is(err, auth.ErrUnauthorized) {
		t.Fatalf("expected ErrUnauthorized, got %v", err)
	}
}

func TestService_Update_BumpsRowSeq(t *testing.T) {
	repo := newFakeRepo()
	pub := &captureEvents{}
	svc := tenancy.NewService(repo, pub)
	t1, _ := svc.Create(context.Background(), "acme", "Acme", nil)
	ctx := auth.ContextWithTenant(context.Background(), t1.ID)
	newName := "Renamed"
	got, err := svc.Update(ctx, t1.ID, 1, tenancy.UpdatePatch{Name: &newName})
	if err != nil {
		t.Fatalf("Update: %v", err)
	}
	if got.RowSeq != 2 || got.Name != newName {
		t.Fatalf("expected row_seq=2 name=Renamed, got %+v", got)
	}
	if pub.events[len(pub.events)-1].eventType != "tenant.updated" {
		t.Fatalf("expected tenant.updated, got %#v", pub.events)
	}
}

func TestService_Update_StaleETagMismatch(t *testing.T) {
	repo := newFakeRepo()
	svc := tenancy.NewService(repo, &captureEvents{})
	t1, _ := svc.Create(context.Background(), "acme", "Acme", nil)
	ctx := auth.ContextWithTenant(context.Background(), t1.ID)
	newName := "Once"
	_, _ = svc.Update(ctx, t1.ID, 1, tenancy.UpdatePatch{Name: &newName})

	_, err := svc.Update(ctx, t1.ID, 1, tenancy.UpdatePatch{Name: &newName})
	if !errors.Is(err, tenancy.ErrETagMismatch) {
		t.Fatalf("expected ErrETagMismatch, got %v", err)
	}
}

func TestService_Update_SuspendedEmitsSpecificEvent(t *testing.T) {
	repo := newFakeRepo()
	pub := &captureEvents{}
	svc := tenancy.NewService(repo, pub)
	t1, _ := svc.Create(context.Background(), "acme", "Acme", nil)
	ctx := auth.ContextWithTenant(context.Background(), t1.ID)
	st := tenancy.StatusSuspended
	if _, err := svc.Update(ctx, t1.ID, 1, tenancy.UpdatePatch{Status: &st}); err != nil {
		t.Fatalf("Update: %v", err)
	}
	last := pub.events[len(pub.events)-1].eventType
	if last != "tenant.suspended" {
		t.Fatalf("expected tenant.suspended, got %q", last)
	}
}

func TestService_SoftDelete_Lifecycle(t *testing.T) {
	repo := newFakeRepo()
	pub := &captureEvents{}
	svc := tenancy.NewService(repo, pub)
	t1, _ := svc.Create(context.Background(), "acme", "Acme", nil)
	ctx := auth.ContextWithTenant(context.Background(), t1.ID)
	if err := svc.SoftDelete(ctx, t1.ID, 1); err != nil {
		t.Fatalf("SoftDelete: %v", err)
	}
	if pub.events[len(pub.events)-1].eventType != "tenant.deleted" {
		t.Fatalf("expected tenant.deleted event")
	}
	if _, err := repo.Get(ctx, t1.ID); !errors.Is(err, tenancy.ErrNotFound) {
		t.Fatalf("soft-deleted tenant should be invisible to Get")
	}
}
