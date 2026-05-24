package tenancy

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
)

// PgxRepository is the pgx-backed Repository implementation. It owns the
// sqlc Queries and translates the generated types into the domain Tenant.
//
// The pool's AfterAcquire hook is expected to have already set
// `SET LOCAL app.current_tenant_id = $tenant` on every connection (defense
// layer 3 of tenant isolation). Without that hook, RLS silently returns
// empty result sets — see anti-pattern guards in 03-tenants-slice.md.
type PgxRepository struct {
	q *db.Queries
}

// NewPgxRepository constructs a Repository over the given sqlc Queries.
func NewPgxRepository(q *db.Queries) *PgxRepository {
	return &PgxRepository{q: q}
}

// Create inserts a tenant. Returns ErrSlugTaken on UNIQUE collision.
func (r *PgxRepository) Create(ctx context.Context, t Tenant) (Tenant, error) {
	metaJSON, err := marshalMetadata(t.Metadata)
	if err != nil {
		return Tenant{}, err
	}
	row, err := r.q.CreateTenant(ctx, db.CreateTenantParams{
		ID:       t.ID,
		Slug:     t.Slug,
		Name:     t.Name,
		Metadata: metaJSON,
	})
	if err != nil {
		if isUniqueViolation(err) {
			return Tenant{}, ErrSlugTaken
		}
		return Tenant{}, err
	}
	return mapTenant(row)
}

// Get returns the row matching id, or ErrNotFound. Soft-deleted rows are
// invisible to this query.
func (r *PgxRepository) Get(ctx context.Context, id string) (Tenant, error) {
	row, err := r.q.GetTenant(ctx, id)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Tenant{}, ErrNotFound
		}
		return Tenant{}, err
	}
	return mapTenant(row)
}

// GetBySlug returns the row matching slug, or ErrNotFound.
func (r *PgxRepository) GetBySlug(ctx context.Context, slug string) (Tenant, error) {
	row, err := r.q.GetTenantBySlug(ctx, slug)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Tenant{}, ErrNotFound
		}
		return Tenant{}, err
	}
	return mapTenant(row)
}

// List returns up to limit rows newer than the cursor. The boolean reports
// has_more by asking for limit+1 rows from the underlying SELECT.
func (r *PgxRepository) List(ctx context.Context, limit int, cursor *ListCursor) ([]Tenant, bool, error) {
	if limit <= 0 || limit > 200 {
		limit = 25
	}
	params := db.ListTenantsParams{RowLimit: int32(limit + 1)}
	if cursor != nil {
		params.CursorCreatedAt = pgtype.Timestamptz{Time: cursor.CreatedAt, Valid: true}
		cursorID := cursor.ID
		params.CursorID = &cursorID
	}
	rows, err := r.q.ListTenants(ctx, params)
	if err != nil {
		return nil, false, err
	}
	hasMore := len(rows) > limit
	if hasMore {
		rows = rows[:limit]
	}
	out := make([]Tenant, 0, len(rows))
	for _, row := range rows {
		t, err := mapTenant(row)
		if err != nil {
			return nil, false, err
		}
		out = append(out, t)
	}
	return out, hasMore, nil
}

// Update applies the patch under optimistic concurrency. Returns
// ErrETagMismatch when expectedSeq does not match the current row_seq.
func (r *PgxRepository) Update(ctx context.Context, idStr string, expectedSeq int64, patch UpdatePatch) (Tenant, error) {
	params := db.UpdateTenantParams{
		ID:     idStr,
		RowSeq: expectedSeq,
	}
	if patch.Name != nil {
		params.Name = patch.Name
	}
	if patch.Status != nil {
		s := string(*patch.Status)
		params.Status = &s
	}
	if patch.PatchMetadata {
		metaJSON, err := marshalMetadata(patch.Metadata)
		if err != nil {
			return Tenant{}, err
		}
		params.Metadata = metaJSON
	}
	row, err := r.q.UpdateTenant(ctx, params)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			// Either the row is gone or row_seq did not match. Distinguish by
			// re-reading: if the row exists, it's an ETag mismatch.
			if _, gerr := r.q.GetTenant(ctx, idStr); gerr == nil {
				return Tenant{}, ErrETagMismatch
			}
			return Tenant{}, ErrNotFound
		}
		return Tenant{}, err
	}
	return mapTenant(row)
}

// SoftDelete flips status to "deleted" and stamps deleted_at. Optimistic
// concurrency mirrors Update.
func (r *PgxRepository) SoftDelete(ctx context.Context, idStr string, expectedSeq int64) (Tenant, error) {
	row, err := r.q.SoftDeleteTenant(ctx, db.SoftDeleteTenantParams{
		ID:     idStr,
		RowSeq: expectedSeq,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			if _, gerr := r.q.GetTenant(ctx, idStr); gerr == nil {
				return Tenant{}, ErrETagMismatch
			}
			return Tenant{}, ErrNotFound
		}
		return Tenant{}, err
	}
	return mapTenant(row)
}

func mapTenant(row db.Tenant) (Tenant, error) {
	meta := map[string]string{}
	if len(row.Metadata) > 0 {
		if err := json.Unmarshal(row.Metadata, &meta); err != nil {
			return Tenant{}, err
		}
	}
	var deletedAt *time.Time
	if row.DeletedAt.Valid {
		t := row.DeletedAt.Time
		deletedAt = &t
	}
	return Tenant{
		ID:                    row.ID,
		Slug:                  row.Slug,
		Name:                  row.Name,
		Status:                Status(row.Status),
		DefaultOrganizationID: row.DefaultOrganizationID,
		Metadata:              meta,
		RowSeq:                row.RowSeq,
		CreatedAt:             row.CreatedAt.Time.UTC(),
		UpdatedAt:             row.UpdatedAt.Time.UTC(),
		DeletedAt:             deletedAt,
	}, nil
}

func marshalMetadata(m map[string]string) ([]byte, error) {
	if m == nil {
		m = map[string]string{}
	}
	return json.Marshal(m)
}

// isUniqueViolation detects a Postgres unique_violation (SQLSTATE 23505)
// without importing the pgconn types into every callsite. A string match on
// the canonical error text is sufficient for sqlc's wrapped errors.
func isUniqueViolation(err error) bool {
	if err == nil {
		return false
	}
	return strings.Contains(err.Error(), "23505") ||
		strings.Contains(strings.ToLower(err.Error()), "duplicate key")
}
