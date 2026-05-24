package tenancy

import (
	"context"
	"time"
)

// Repository abstracts persistence so the service can be unit-tested without
// a real Postgres. The pgx implementation lives in repo_pgx.go; tests
// substitute a mocked repository.
type Repository interface {
	Create(ctx context.Context, t Tenant) (Tenant, error)
	Get(ctx context.Context, id string) (Tenant, error)
	GetBySlug(ctx context.Context, slug string) (Tenant, error)
	List(ctx context.Context, limit int, cursor *ListCursor) ([]Tenant, bool, error)
	Update(ctx context.Context, id string, expectedSeq int64, patch UpdatePatch) (Tenant, error)
	SoftDelete(ctx context.Context, id string, expectedSeq int64) (Tenant, error)
}

// ListCursor is the decoded form of the opaque cursor. Repository.List uses
// (CreatedAt, ID) as a strict tuple less-than to keyset-paginate.
type ListCursor struct {
	CreatedAt time.Time
	ID        string
}

// EventPublisher is the outbox port. Implementations write to outbox_event
// in the same transaction as the state change (real implementation lands in
// Phase 3 once the transactional context is promoted; Phase 2 ships a logger
// publisher in cmd/dataplane/main.go).
type EventPublisher interface {
	Publish(ctx context.Context, eventType, tenantID string, payload map[string]any) error
}
