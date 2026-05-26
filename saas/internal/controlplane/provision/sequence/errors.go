package sequence

import "errors"

// Sentinel errors. The handler layer maps these to RFC 7807 problem
// types; keep stable so the type slug in the problem document stays
// constant across releases.
var (
	// ErrAdapterNil signals a Sequence constructed without one of the
	// four required adapters. Programmer error; surfaces as a 500 with
	// the missing adapter name.
	ErrAdapterNil = errors.New("sequence: adapter not configured")

	// ErrStepFailed wraps the underlying adapter error after a step's
	// Run callback returns non-nil. The orchestrator marks the step
	// 'failed' in the ledger before returning the wrap.
	ErrStepFailed = errors.New("sequence: step failed")

	// ErrRollbackFailed signals a rollback chain failure. The deployment
	// is escalated to status='corrupted' and the destroy reconciler
	// retries on a longer back-off.
	ErrRollbackFailed = errors.New("sequence: rollback failed")

	// ErrCannotDowngrade — Upgrade refused because the target image is
	// equal-or-lower than the current per semver compare. Bypass requires
	// a manual SQL UPDATE on deployment.image_version (operator-pain
	// trip-wire by design).
	ErrCannotDowngrade = errors.New("sequence: cannot downgrade image_version")

	// ErrCannotPurgeActive — Purge refused because the deployment is
	// not in 'destroyed' or 'failed' state. Operators must soft-delete
	// first; Purge is the physical-delete-now escape hatch.
	ErrCannotPurgeActive = errors.New("sequence: cannot purge active deployment")

	// ErrPITROutOfRange — Restore refused because the requested PITR
	// timestamp is outside the WAL archive window.
	ErrPITROutOfRange = errors.New("sequence: pitr timestamp out of range")

	// ErrInvalidImageVersion — image_version did not match the
	// ^v\d+\.\d+\.\d+(-[A-Za-z0-9.-]+)?$ shape. Strict by design — the
	// value lands in container image tags + audit rows.
	ErrInvalidImageVersion = errors.New("sequence: invalid image_version")

	// ErrHealthCheckFailed — the public /healthz probe never returned
	// 200 within the configured timeout.
	ErrHealthCheckFailed = errors.New("sequence: healthz did not return 200")

	// ErrPreviousRevisionMissing — Rollback called when no prior
	// revision row exists. Surfaces as 422.
	ErrPreviousRevisionMissing = errors.New("sequence: no previous revision to roll back to")

	// ErrRestoreNotImplemented — the backup adapter is a stub for MVP.
	// Phase 12e plan §12e.7 documents the actual pg_basebackup +
	// pg_restore + WAL replay path; until host-level WAL archiving is
	// wired, restore returns this sentinel.
	ErrRestoreNotImplemented = errors.New("sequence: restore requires host wal archiving (out of mvp)")
)
