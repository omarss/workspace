package audit

import "context"

// Repository is the persistence port for the audit_event table. Per
// CONVENTIONS.md §1 the interface is intentionally narrow — the service
// composes the methods to express each verb. The pgx-backed
// implementation lives in repo_pgx.go; the in-memory implementation in
// repo_memory.go drives unit tests without spinning up Postgres.
type Repository interface {
	// Append inserts a new row at the head of tenantID's chain. The
	// repository looks up the current head, computes the next
	// chain_sequence + prev_hash + row_hash, and INSERTS — all under a
	// per-tenant lock so concurrent appends produce a deterministic
	// chain.
	//
	// Returns ErrChainRace when the lookup-then-insert race window is
	// lost; the caller is expected to retry.
	//
	// SourceEventID, when non-empty, is used as an idempotency token:
	// re-appending the same outbox event is a no-op that returns the
	// existing row.
	Append(ctx context.Context, in NewEventInput) (Event, error)

	// Get fetches a single row by id. Returns ErrNotFound when no row
	// exists for that tenant/id pair. RLS makes the cross-tenant case
	// and the genuinely-not-found case indistinguishable, by design.
	Get(ctx context.Context, tenantID, eventID string) (Event, error)

	// List streams up to filter.Limit rows in occurred_at-descending
	// order, applying the optional filters. Returns hasMore=true when
	// the underlying query saw more rows than were returned.
	List(ctx context.Context, filter ListFilter) (events []Event, hasMore bool, err error)

	// StreamForVerify yields every row for the optional tenant filter
	// in (tenant_id, chain_sequence) ascending order so the verifier
	// walks each tenant's chain start-to-finish. fn is invoked
	// row-at-a-time; returning a non-nil error short-circuits the
	// iteration.
	StreamForVerify(ctx context.Context, tenantFilter string, fn func(Event) error) error
}
