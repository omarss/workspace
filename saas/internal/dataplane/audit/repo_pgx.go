package audit

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/omarss/saas/internal/platform/id"
)

// PgxRepository is the pgx-backed Repository for audit_event rows. The
// hash chain math runs in Go (this package); the database is responsible
// only for sequencing per-tenant inserts and rejecting UPDATE / DELETE
// via the triggers in migrations/dataplane/000008_audit.up.sql.
//
// Concurrency: Append uses a SERIALIZABLE transaction with a per-tenant
// advisory lock so two concurrent appends on the same tenant cannot
// race on the chain head. The advisory lock is keyed on a hash of
// tenant_id and is released on tx commit / rollback.
type PgxRepository struct {
	pool *pgxpool.Pool
}

// NewPgxRepository constructs a PgxRepository.
func NewPgxRepository(pool *pgxpool.Pool) *PgxRepository {
	return &PgxRepository{pool: pool}
}

const auditCols = `id, tenant_id, actor_type, actor_id, action, resource_type, resource_id,
    occurred_at, ip_address, user_agent, request_id, metadata, source_event_id,
    prev_hash, row_hash, chain_sequence`

// Append implements Repository. The transaction body:
//
//  1. Acquires a session-level advisory xact lock keyed on tenant_id —
//     mutual exclusion against other appenders on the same tenant.
//  2. Idempotency check via the unique partial index on source_event_id;
//     if the event already exists, returns it without inserting.
//  3. Reads the current chain head (highest chain_sequence) FOR UPDATE
//     so even a misconfigured isolation level cannot race.
//  4. Computes prev_hash + row_hash in Go.
//  5. INSERT.
//
// On serialization failure the caller is expected to retry; the
// subscriber-side retry loop wraps Append accordingly.
func (r *PgxRepository) Append(ctx context.Context, in NewEventInput) (Event, error) {
	if err := validateNewEvent(in); err != nil {
		return Event{}, err
	}
	tx, err := r.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
	if err != nil {
		return Event{}, fmt.Errorf("audit: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	// pg_advisory_xact_lock takes a bigint key; hashtext yields a stable
	// int32 we widen with a constant tag so we cannot collide with other
	// callers that use the same advisory-lock namespace.
	if _, err := tx.Exec(ctx,
		`SELECT pg_advisory_xact_lock(hashtext($1)::bigint, $2::bigint)`,
		in.TenantID, int64(0xa5d17)); err != nil {
		return Event{}, fmt.Errorf("audit: advisory lock: %w", err)
	}

	// Idempotency short-circuit. The partial UNIQUE index on
	// source_event_id catches the cross-tx case; this in-tx check is for
	// a same-process retry inside the same lock window.
	if in.SourceEventID != "" {
		existing, found, err := r.findBySourceEventID(ctx, tx, in.SourceEventID)
		if err != nil {
			return Event{}, err
		}
		if found {
			if err := tx.Commit(ctx); err != nil {
				return Event{}, fmt.Errorf("audit: commit idempotent: %w", err)
			}
			return existing, nil
		}
	}

	var prevHash []byte
	var nextSeq int64 = 1
	row := tx.QueryRow(ctx,
		`SELECT row_hash, chain_sequence
           FROM audit_event
          WHERE tenant_id = $1
          ORDER BY chain_sequence DESC
          LIMIT 1
          FOR UPDATE`,
		in.TenantID)
	var headHash []byte
	var headSeq int64
	scanErr := row.Scan(&headHash, &headSeq)
	switch {
	case scanErr == nil:
		prevHash = headHash
		nextSeq = headSeq + 1
	case errors.Is(scanErr, pgx.ErrNoRows):
		prevHash = Genesis(in.TenantID)
	default:
		return Event{}, fmt.Errorf("audit: read chain head: %w", scanErr)
	}

	occurredAt := in.OccurredAt
	if occurredAt.IsZero() {
		occurredAt = time.Now().UTC()
	}
	ev := Event{
		ID:            id.New(id.PrefixAudit),
		TenantID:      in.TenantID,
		ActorType:     in.ActorType,
		ActorID:       in.ActorID,
		Action:        in.Action,
		ResourceType:  in.ResourceType,
		ResourceID:    in.ResourceID,
		OccurredAt:    occurredAt.UTC(),
		IPAddress:     in.IPAddress,
		UserAgent:     in.UserAgent,
		RequestID:     in.RequestID,
		Metadata:      copyMetadata(in.Metadata),
		SourceEventID: in.SourceEventID,
		PrevHash:      prevHash,
		ChainSequence: nextSeq,
	}
	rh, err := ComputeRowHash(prevHash, ev.CanonicalBody())
	if err != nil {
		return Event{}, fmt.Errorf("audit: compute row_hash: %w", err)
	}
	ev.RowHash = rh

	metaJSON, err := json.Marshal(ev.Metadata)
	if err != nil {
		return Event{}, fmt.Errorf("audit: marshal metadata: %w", err)
	}

	const insert = `
INSERT INTO audit_event
    (id, tenant_id, actor_type, actor_id, action, resource_type, resource_id,
     occurred_at, ip_address, user_agent, request_id, metadata, source_event_id,
     prev_hash, row_hash, chain_sequence)
VALUES ($1,$2,$3,$4,$5,$6,NULLIF($7,''),
        $8, NULLIF($9,''), NULLIF($10,''), NULLIF($11,''), $12, NULLIF($13,''),
        $14, $15, $16)
`
	if _, err := tx.Exec(ctx, insert,
		ev.ID, ev.TenantID, string(ev.ActorType), ev.ActorID, ev.Action,
		ev.ResourceType, ev.ResourceID,
		ev.OccurredAt, ev.IPAddress, ev.UserAgent, ev.RequestID, metaJSON, ev.SourceEventID,
		ev.PrevHash, ev.RowHash, ev.ChainSequence,
	); err != nil {
		return Event{}, fmt.Errorf("audit: insert: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return Event{}, fmt.Errorf("audit: commit: %w", err)
	}
	return ev, nil
}

// Get implements Repository.
func (r *PgxRepository) Get(ctx context.Context, tenantID, eventID string) (Event, error) {
	row := r.pool.QueryRow(ctx,
		`SELECT `+auditCols+` FROM audit_event WHERE id = $1 AND tenant_id = $2`,
		eventID, tenantID)
	ev, err := scanEvent(row)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Event{}, ErrNotFound
		}
		return Event{}, fmt.Errorf("audit: get: %w", err)
	}
	return ev, nil
}

// List implements Repository.
func (r *PgxRepository) List(ctx context.Context, filter ListFilter) ([]Event, bool, error) {
	limit := filter.Limit
	if limit <= 0 {
		limit = 25
	}
	args := []any{filter.TenantID, limit + 1}
	var where strings.Builder
	where.WriteString(` WHERE tenant_id = $1`)
	idx := 3
	if filter.Action != "" {
		args = append(args, filter.Action)
		fmt.Fprintf(&where, ` AND action = $%d`, idx)
		idx++
	}
	if filter.ResourceType != "" {
		args = append(args, filter.ResourceType)
		fmt.Fprintf(&where, ` AND resource_type = $%d`, idx)
		idx++
	}
	if filter.ResourceID != "" {
		args = append(args, filter.ResourceID)
		fmt.Fprintf(&where, ` AND resource_id = $%d`, idx)
		idx++
	}
	if filter.ActorID != "" {
		args = append(args, filter.ActorID)
		fmt.Fprintf(&where, ` AND actor_id = $%d`, idx)
		idx++
	}
	if !filter.OccurredFrom.IsZero() {
		args = append(args, filter.OccurredFrom)
		fmt.Fprintf(&where, ` AND occurred_at >= $%d`, idx)
		idx++
	}
	if !filter.OccurredTo.IsZero() {
		args = append(args, filter.OccurredTo)
		fmt.Fprintf(&where, ` AND occurred_at <= $%d`, idx)
	}
	stmt := `SELECT ` + auditCols + ` FROM audit_event` + where.String() +
		` ORDER BY occurred_at DESC, chain_sequence DESC LIMIT $2`
	rows, err := r.pool.Query(ctx, stmt, args...)
	if err != nil {
		return nil, false, fmt.Errorf("audit: list: %w", err)
	}
	defer rows.Close()
	out := make([]Event, 0, limit)
	for rows.Next() {
		ev, err := scanEvent(rows)
		if err != nil {
			return nil, false, fmt.Errorf("audit: list scan: %w", err)
		}
		out = append(out, ev)
	}
	if err := rows.Err(); err != nil {
		return nil, false, fmt.Errorf("audit: list rows: %w", err)
	}
	hasMore := len(out) > limit
	if hasMore {
		out = out[:limit]
	}
	return out, hasMore, nil
}

// StreamForVerify implements Repository. The chain order is
// (tenant_id, chain_sequence) ASC so the verifier walks every tenant's
// chain start-to-finish without an extra pass.
func (r *PgxRepository) StreamForVerify(ctx context.Context, tenantFilter string, fn func(Event) error) error {
	stmt := `SELECT ` + auditCols + ` FROM audit_event
            WHERE ($1 = '' OR tenant_id = $1)
            ORDER BY tenant_id ASC, chain_sequence ASC`
	rows, err := r.pool.Query(ctx, stmt, tenantFilter)
	if err != nil {
		return fmt.Errorf("audit: verify stream: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		ev, err := scanEvent(rows)
		if err != nil {
			return fmt.Errorf("audit: verify scan: %w", err)
		}
		if err := fn(ev); err != nil {
			return err
		}
	}
	return rows.Err()
}

// findBySourceEventID returns the row matching source_event_id, scoped
// to the current tx. Used by Append's idempotency check.
func (r *PgxRepository) findBySourceEventID(ctx context.Context, tx pgx.Tx, sourceEventID string) (Event, bool, error) {
	row := tx.QueryRow(ctx,
		`SELECT `+auditCols+` FROM audit_event WHERE source_event_id = $1`,
		sourceEventID)
	ev, err := scanEvent(row)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Event{}, false, nil
		}
		return Event{}, false, fmt.Errorf("audit: idempotent lookup: %w", err)
	}
	return ev, true, nil
}

// scanRow is the common surface pgx.Row and pgx.Rows share.
type scanRow interface {
	Scan(dest ...any) error
}

func scanEvent(s scanRow) (Event, error) {
	var (
		ev            Event
		resourceID    *string
		ipAddress     *string
		userAgent     *string
		requestID     *string
		sourceEventID *string
		metaJSON      []byte
		actorType     string
	)
	if err := s.Scan(
		&ev.ID, &ev.TenantID, &actorType, &ev.ActorID, &ev.Action,
		&ev.ResourceType, &resourceID,
		&ev.OccurredAt, &ipAddress, &userAgent, &requestID, &metaJSON, &sourceEventID,
		&ev.PrevHash, &ev.RowHash, &ev.ChainSequence,
	); err != nil {
		return Event{}, err
	}
	ev.ActorType = ActorType(actorType)
	if resourceID != nil {
		ev.ResourceID = *resourceID
	}
	if ipAddress != nil {
		ev.IPAddress = *ipAddress
	}
	if userAgent != nil {
		ev.UserAgent = *userAgent
	}
	if requestID != nil {
		ev.RequestID = *requestID
	}
	if sourceEventID != nil {
		ev.SourceEventID = *sourceEventID
	}
	if len(metaJSON) > 0 {
		var m map[string]any
		if err := json.Unmarshal(metaJSON, &m); err != nil {
			return Event{}, fmt.Errorf("audit: unmarshal metadata: %w", err)
		}
		ev.Metadata = m
	} else {
		ev.Metadata = map[string]any{}
	}
	return ev, nil
}
