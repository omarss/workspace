package identity

import "errors"

// Domain-level sentinel errors. The handler translates these into RFC 9457
// Problem Details responses; the repository emits them for the common
// not-found / conflict / concurrency-violation cases.
var (
	// ErrNotFound — no row matched the lookup or the row is soft-deleted.
	ErrNotFound = errors.New("identity: user not found")
	// ErrEmailTaken — UNIQUE (tenant_id, email_lookup_hash) rejected an insert.
	ErrEmailTaken = errors.New("identity: email already taken in this tenant")
	// ErrETagMismatch — UPDATE WHERE row_seq = $expected returned zero rows.
	// HTTP layer surfaces this as 412 Precondition Failed.
	ErrETagMismatch = errors.New("identity: etag mismatch")
	// ErrInvalidInput — domain-level validation (email format, status enum, etc.).
	// Handler surfaces as 422.
	ErrInvalidInput = errors.New("identity: invalid input")
	// ErrInvalidProvider — social provider not in the MVP allowlist (google,
	// github, apple). 422.
	ErrInvalidProvider = errors.New("identity: invalid social provider")
	// ErrUserDisabled — operation refused because the target user is disabled.
	ErrUserDisabled = errors.New("identity: user is disabled")
	// ErrStateExpired — social-login state row expired before consumption.
	ErrStateExpired = errors.New("identity: social login state expired")
	// ErrStateAlreadyUsed — replay attempt on a social-login state row.
	ErrStateAlreadyUsed = errors.New("identity: social login state already used")
	// ErrProviderUnavailable — gocloak adapter returned a non-recoverable error.
	// Indicates a Keycloak misconfiguration; handler surfaces as 502/503.
	ErrProviderUnavailable = errors.New("identity: identity provider unavailable")
)
