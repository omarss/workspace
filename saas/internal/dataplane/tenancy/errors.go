package tenancy

import "errors"

// Domain-level sentinel errors. The handler translates these into RFC 9457
// Problem Details responses; the repository emits these for the common
// "not-found / conflict / concurrency-violation" cases.
var (
	// ErrNotFound — no row matched the lookup or the row is soft-deleted.
	ErrNotFound = errors.New("tenant not found")
	// ErrSlugTaken — UNIQUE index on tenant.slug rejected an insert.
	ErrSlugTaken = errors.New("tenant slug already taken")
	// ErrETagMismatch — UPDATE WHERE row_seq = $expected returned zero rows.
	// HTTP layer surfaces this as 412 Precondition Failed.
	ErrETagMismatch = errors.New("etag mismatch")
	// ErrInvalidInput — domain-level validation (slug pattern, status enum,
	// metadata size). Handler surfaces as 422.
	ErrInvalidInput = errors.New("invalid tenant input")
)
