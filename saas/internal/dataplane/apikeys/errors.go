package apikeys

import "errors"

// Sentinel errors. Handlers map these to RFC 9457 problem responses via
// the central catalogue in internal/platform/problem (CONVENTIONS.md §3).
//
// The mapping per the table:
//
//	ErrNotFound          → 404 not-found
//	ErrETagMismatch      → 412 precondition-failed
//	ErrInvalidInput      → 422 validation-error
//	ErrGraceOutOfRange   → 422 validation-error
//	ErrNotRotatable      → 422 validation-error
//	ErrKeyRevoked        → 401 api-key-revoked     (auth-path mapping)
//	ErrKeyExpired        → 401 api-key-expired     (auth-path mapping)
//	ErrIPNotAllowed      → 403 ip-not-allowlisted
//	ErrBearerMalformed   → 401 unauthorized
var (
	// ErrNotFound — no row with the requested id (or row exists in
	// another tenant, which returns the same shape so existence
	// doesn't leak across tenants).
	ErrNotFound = errors.New("apikeys: api key not found")
	// ErrETagMismatch — caller supplied If-Match that does not match
	// the current row_seq.
	ErrETagMismatch = errors.New("apikeys: etag mismatch")
	// ErrInvalidInput — domain validation failed (empty name, scope
	// pattern mismatch, etc.).
	ErrInvalidInput = errors.New("apikeys: invalid input")
	// ErrGraceOutOfRange — rotate request supplied a
	// grace_period_seconds outside [0, GracePeriodMax].
	ErrGraceOutOfRange = errors.New("apikeys: grace period out of range")
	// ErrNotRotatable — caller asked to rotate a non-active row
	// (revoked, expired). The 422 response surfaces the precise
	// reason via the detail field.
	ErrNotRotatable = errors.New("apikeys: key is not in a rotatable state")
	// ErrBearerMalformed — the auth path could not parse the bearer
	// into env_prefix_random tuple.
	ErrBearerMalformed = errors.New("apikeys: malformed bearer")
	// ErrInvalidCIDR — an entry in ip_allowlist could not be parsed
	// as a CIDR block.
	ErrInvalidCIDR = errors.New("apikeys: invalid CIDR in ip_allowlist")
)
