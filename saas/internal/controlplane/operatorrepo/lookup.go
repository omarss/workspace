// Package operatorrepo binds the sqlc-generated controlplane queries to
// the small OperatorLookup interface consumed by the IP-allowlist
// middleware. Keeping the adapter in its own package avoids a circular
// import: operatorjwt -> operatorrepo -> db (sqlc), with operatorrepo
// owning the only direct dependency on the sqlc generator output.
//
// The lookup also surfaces a GetByID and ListActive for the saasctl
// operator subtree (Phase 14+ will lean on this).
package operatorrepo

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"

	db "github.com/omarss/saas/internal/controlplane/db/sqlc"
)

// Querier is the read surface we need. Both *db.Queries and the test
// fake satisfy this; intentionally narrower than db.Querier so changes
// to the generator output don't ripple through.
type Querier interface {
	GetOperatorByID(ctx context.Context, id string) (db.GetOperatorByIDRow, error)
	GetOperatorByKeycloakUserID(ctx context.Context, kcID *string) (db.GetOperatorByKeycloakUserIDRow, error)
	ListActiveOperators(ctx context.Context) ([]db.ListActiveOperatorsRow, error)
}

// Lookup is the concrete adapter wired in cmd/controlplane.
type Lookup struct {
	q Querier
}

// New wraps q. q must be non-nil.
func New(q Querier) *Lookup {
	if q == nil {
		panic("operatorrepo: nil querier")
	}
	return &Lookup{q: q}
}

// GetOperatorIPAllowlist implements operatorjwt.OperatorLookup.
//
// Errors:
//   - pgx.ErrNoRows => returns ("", ErrNotFound) so the middleware
//     can refuse the request without revealing the absence.
//   - any other DB error => bubbled through.
func (l *Lookup) GetOperatorIPAllowlist(ctx context.Context, operatorID string) ([]string, error) {
	if operatorID == "" {
		return nil, errors.New("operatorrepo: empty operatorID")
	}
	row, err := l.q.GetOperatorByID(ctx, operatorID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	if !row.IsActive {
		return nil, ErrInactive
	}
	return row.IpAllowlist, nil
}

// ErrNotFound is returned when the JWT subject does not match any
// operator row. The middleware translates this into a 401 — we
// deliberately do not leak "no such operator" vs "wrong CIDR".
var ErrNotFound = errors.New("operatorrepo: operator not found")

// ErrInactive is returned when the operator row exists but is
// suspended. Translated to 401 by the middleware.
var ErrInactive = errors.New("operatorrepo: operator inactive")
