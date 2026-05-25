package audit

import "errors"

// Sentinel errors translated to RFC 9457 problem types in handler.go.
var (
	// ErrNotFound — no row matches the (tenant_id, id) tuple. The
	// repository returns this in lieu of pgx.ErrNoRows so handlers
	// don't import pgx.
	ErrNotFound = errors.New("audit: event not found")

	// ErrInvalidInput — subscriber received an event with missing
	// required fields (tenant_id / actor_id / action). The subscriber
	// logs and skips rather than blocking the whole outbox.
	ErrInvalidInput = errors.New("audit: invalid event input")

	// ErrChainRace — the repository detected a concurrent insert
	// changed the chain head mid-flight. The caller (subscriber) is
	// expected to retry; this is not surfaced to API clients.
	ErrChainRace = errors.New("audit: chain head changed during insert")

	// ErrExportTooLarge — sync export exceeded the inline size budget
	// (1MB heuristic). The handler converts this to a 413 with a
	// pointer to the async export job.
	ErrExportTooLarge = errors.New("audit: export exceeds sync budget")
)
