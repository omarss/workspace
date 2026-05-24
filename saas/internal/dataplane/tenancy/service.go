package tenancy

import (
	"context"
	"errors"
	"regexp"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/id"
)

// slugPattern mirrors the OpenAPI schema. Re-validated server-side so the
// service refuses input even if the request-validator middleware is bypassed
// (defense in depth — never trust the spec validator alone).
var slugPattern = regexp.MustCompile(`^[a-z][a-z0-9-]*[a-z0-9]$`)

// nameMaxLen / metadataMaxValueLen mirror the OpenAPI constraints. Repeated
// here so the service rejects bad input even when the request-validator
// middleware is bypassed in tests.
const (
	slugMinLen          = 2
	slugMaxLen          = 32
	nameMinLen          = 1
	nameMaxLen          = 120
	metadataMaxKeys     = 16
	metadataValueMaxLen = 256
)

// Service is the tenancy application service. It validates input, calls the
// repository, and emits domain events through the outbox port.
type Service struct {
	repo   Repository
	events EventPublisher
	now    func() time.Time
}

// NewService constructs a Service. The time function is overridable so unit
// tests can use a deterministic clock.
func NewService(repo Repository, events EventPublisher) *Service {
	return &Service{repo: repo, events: events, now: time.Now}
}

// WithClock replaces the clock used for CreatedAt / UpdatedAt. Tests only.
func (s *Service) WithClock(now func() time.Time) *Service {
	s.now = now
	return s
}

// Create makes a new tenant.
//
// Layer-2 note (eight-layer tenant isolation): Tenants is the one module
// whose tenant_id IS its primary id. Service.Create therefore does NOT take
// a tenantID parameter — the row being created defines its own tenant.
// Every OTHER module's Service.Create signature MUST take tenantID as the
// first non-context argument (organisations, api-keys, members, ...).
func (s *Service) Create(ctx context.Context, slug, name string, metadata map[string]string) (Tenant, error) {
	if err := validateSlug(slug); err != nil {
		return Tenant{}, err
	}
	if err := validateName(name); err != nil {
		return Tenant{}, err
	}
	if err := validateMetadata(metadata); err != nil {
		return Tenant{}, err
	}

	// Pre-check for a friendlier 422 instead of leaking the DB UNIQUE error.
	// The constraint still backs us up on a race.
	if existing, err := s.repo.GetBySlug(ctx, slug); err == nil && existing.ID != "" {
		return Tenant{}, ErrSlugTaken
	} else if err != nil && !errors.Is(err, ErrNotFound) {
		return Tenant{}, err
	}

	t := Tenant{
		ID:        id.New(id.PrefixTenant),
		Slug:      slug,
		Name:      name,
		Status:    StatusActive,
		Metadata:  metadata,
		RowSeq:    1,
		CreatedAt: s.now().UTC(),
		UpdatedAt: s.now().UTC(),
	}
	created, err := s.repo.Create(ctx, t)
	if err != nil {
		return Tenant{}, err
	}
	// Outbox publish failures must NOT roll back the state change in Phase 2
	// (no transactional outbox yet; promoted in Phase 3). The event is
	// best-effort — see service_test.go for the regression test that protects
	// this behaviour.
	_ = s.events.Publish(ctx, "tenant.created", created.ID, map[string]any{
		"tenant_id": created.ID,
		"slug":      created.Slug,
		"name":      created.Name,
	})
	return created, nil
}

// Get returns a tenant if and only if the caller's auth context matches the
// requested resource id (layer 1). Returns ErrUnauthorized when no tenant in
// context, ErrCrossTenant otherwise.
func (s *Service) Get(ctx context.Context, tenantID string) (Tenant, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Tenant{}, err
	}
	return s.repo.Get(ctx, tenantID)
}

// List returns the caller's tenant (one element) in Phase 2. Cross-tenant
// listing is reserved for operator impersonation in Phase 13.
func (s *Service) List(ctx context.Context, limit int, _ *ListCursor) ([]Tenant, bool, error) {
	caller, ok := auth.TenantFromContext(ctx)
	if !ok {
		return nil, false, auth.ErrUnauthorized
	}
	t, err := s.repo.Get(ctx, caller)
	if err != nil {
		if errors.Is(err, ErrNotFound) {
			// Caller authenticated against a tenant that no longer exists.
			// Treat as empty list, not an error — the client can re-bootstrap.
			return nil, false, nil
		}
		return nil, false, err
	}
	if limit <= 0 {
		limit = 25
	}
	_ = limit // single-element list; cursor unused until cross-tenant landing
	return []Tenant{t}, false, nil
}

// Update applies a patch under optimistic concurrency. expectedSeq is the
// row_seq parsed from the If-Match header; mismatches surface as 412.
func (s *Service) Update(ctx context.Context, tenantID string, expectedSeq int64, patch UpdatePatch) (Tenant, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Tenant{}, err
	}
	if patch.Name != nil {
		if err := validateName(*patch.Name); err != nil {
			return Tenant{}, err
		}
	}
	if patch.Status != nil {
		switch *patch.Status {
		case StatusActive, StatusSuspended:
			// allowed via PATCH; "deleted" is reachable only through DELETE
		default:
			return Tenant{}, ErrInvalidInput
		}
	}
	if patch.PatchMetadata {
		if err := validateMetadata(patch.Metadata); err != nil {
			return Tenant{}, err
		}
	}
	updated, err := s.repo.Update(ctx, tenantID, expectedSeq, patch)
	if err != nil {
		return Tenant{}, err
	}
	eventType := "tenant.updated"
	if patch.Status != nil && *patch.Status == StatusSuspended {
		eventType = "tenant.suspended"
	}
	_ = s.events.Publish(ctx, eventType, updated.ID, map[string]any{"tenant_id": updated.ID})
	return updated, nil
}

// SoftDelete marks the tenant deleted. Retention applies before physical
// purge (purge lands in Phase 18).
func (s *Service) SoftDelete(ctx context.Context, tenantID string, expectedSeq int64) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	deleted, err := s.repo.SoftDelete(ctx, tenantID, expectedSeq)
	if err != nil {
		return err
	}
	_ = s.events.Publish(ctx, "tenant.deleted", deleted.ID, map[string]any{"tenant_id": deleted.ID})
	return nil
}

func validateSlug(slug string) error {
	if len(slug) < slugMinLen || len(slug) > slugMaxLen || !slugPattern.MatchString(slug) {
		return ErrInvalidInput
	}
	return nil
}

func validateName(name string) error {
	if len(name) < nameMinLen || len(name) > nameMaxLen {
		return ErrInvalidInput
	}
	return nil
}

func validateMetadata(m map[string]string) error {
	if len(m) > metadataMaxKeys {
		return ErrInvalidInput
	}
	for _, v := range m {
		if len(v) > metadataValueMaxLen {
			return ErrInvalidInput
		}
	}
	return nil
}
