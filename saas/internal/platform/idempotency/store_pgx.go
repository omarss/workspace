package idempotency

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/jackc/pgx/v5"

	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
)

// PgxStore persists idempotency records in Postgres via sqlc-generated
// queries. RLS keeps records scoped to one tenant.
type PgxStore struct {
	q *db.Queries
}

// NewPgxStore builds a Store over the given Queries handle.
func NewPgxStore(q *db.Queries) *PgxStore { return &PgxStore{q: q} }

// Claim attempts an upsert-style INSERT. When no row is returned, another
// request already owns the slot; we then re-fetch it and report Fresh=false.
func (s *PgxStore) Claim(ctx context.Context, key Key, hash []byte) (ClaimResult, error) {
	row, err := s.q.ClaimIdempotencyRecord(ctx, db.ClaimIdempotencyRecordParams{
		TenantID:        key.TenantID,
		IdempotencyKey:  key.IdempotencyKey,
		Route:           key.Route,
		Method:          key.Method,
		RequestBodyHash: hash,
	})
	if err == nil {
		return ClaimResult{ID: row.ID, Fresh: true, InFlight: true, BodyHash: row.RequestBodyHash}, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return ClaimResult{}, err
	}
	existing, gerr := s.q.GetIdempotencyRecord(ctx, db.GetIdempotencyRecordParams{
		TenantID:       key.TenantID,
		IdempotencyKey: key.IdempotencyKey,
		Route:          key.Route,
		Method:         key.Method,
	})
	if gerr != nil {
		return ClaimResult{}, gerr
	}
	headers := map[string]string{}
	if len(existing.ResponseHeaders) > 0 {
		_ = json.Unmarshal(existing.ResponseHeaders, &headers)
	}
	status := 0
	if existing.ResponseStatus != nil {
		status = int(*existing.ResponseStatus)
	}
	return ClaimResult{
		ID:              existing.ID,
		Fresh:           false,
		InFlight:        existing.InFlight,
		BodyHash:        existing.RequestBodyHash,
		ResponseStatus:  status,
		ResponseHeaders: headers,
		ResponseBody:    existing.ResponseBody,
	}, nil
}

// Finish records the response body / headers / status on the claimed row.
func (s *PgxStore) Finish(ctx context.Context, recordID int64, status int, headers map[string]string, body []byte) error {
	hb, err := json.Marshal(headers)
	if err != nil {
		return err
	}
	if status < 0 || status > 999 {
		// Defensive guard; HTTP status codes are < 1000. Keeps gosec happy on
		// the int → int32 narrowing below.
		status = 500
	}
	st := int32(status) //nolint:gosec // bounds-checked immediately above
	return s.q.FinishIdempotencyRecord(ctx, db.FinishIdempotencyRecordParams{
		ID:              recordID,
		ResponseStatus:  &st,
		ResponseHeaders: hb,
		ResponseBody:    body,
	})
}
