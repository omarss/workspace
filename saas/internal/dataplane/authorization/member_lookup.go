package authorization

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"

	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
)

// PgxMemberLookup is the pgx-backed MemberLookup. The single query is
// GetMemberTenantID — the service uses the result to validate that a
// Check request's member_id actually belongs to the claimed tenant_id
// before consulting the policy enforcer.
//
// The query bypasses the organizations module so authorization doesn't
// depend on organizations at compile time (one-way dependency graph:
// other modules depend on authorization to enforce, not the reverse).
type PgxMemberLookup struct {
	q *db.Queries
}

// NewPgxMemberLookup wires the lookup over sqlc Queries.
func NewPgxMemberLookup(q *db.Queries) *PgxMemberLookup {
	return &PgxMemberLookup{q: q}
}

// GetMemberTenant returns the tenant_id of the given member. Returns
// ErrMemberNotFound when no row exists.
func (l *PgxMemberLookup) GetMemberTenant(ctx context.Context, memberID string) (string, error) {
	tid, err := l.q.GetMemberTenantID(ctx, memberID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return "", ErrMemberNotFound
		}
		return "", err
	}
	return tid, nil
}
