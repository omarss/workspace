package notifications

import "errors"

// Domain-level sentinel errors. The handler maps these into RFC 9457
// Problem Details responses; repository / adapter layers emit them for
// the common not-found / conflict / concurrency / validation cases.
var (
	// ErrNotFound — no row matched the lookup or the row is soft-deleted.
	ErrNotFound = errors.New("notifications: not found")
	// ErrNameTaken — UNIQUE (tenant_id, name) rejected an insert.
	ErrNameTaken = errors.New("notifications: channel name already taken in this tenant")
	// ErrETagMismatch — UPDATE WHERE row_seq = $expected returned zero rows.
	// HTTP layer surfaces this as 412 Precondition Failed.
	ErrETagMismatch = errors.New("notifications: etag mismatch")
	// ErrInvalidInput — domain-level validation (bad enum, oversize, …).
	ErrInvalidInput = errors.New("notifications: invalid input")
	// ErrInvalidProvider — channel provider not in the MVP allowlist.
	ErrInvalidProvider = errors.New("notifications: invalid channel provider")
	// ErrInvalidCredentials — credentials shape does not match the provider.
	ErrInvalidCredentials = errors.New("notifications: invalid credentials shape for provider")
	// ErrNoDefaultChannel — Send called for a workflow with no configured
	// default channel for the required delivery type.
	ErrNoDefaultChannel = errors.New("notifications: no default channel configured")
	// ErrWorkflowNotRegistered — workflow_name has no registry entry.
	ErrWorkflowNotRegistered = errors.New("notifications: workflow not registered")
	// ErrUserNotFound — Send targeted a user_id that does not exist or
	// belongs to a different tenant.
	ErrUserNotFound = errors.New("notifications: target user not found")
	// ErrProviderUnavailable — Novu HTTP adapter returned a non-recoverable
	// transport-layer error. Surfaces as 502 once the spec carries the code.
	ErrProviderUnavailable = errors.New("notifications: novu adapter unavailable")
)
