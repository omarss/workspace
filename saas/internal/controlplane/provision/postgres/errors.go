package postgres

import "errors"

// Sentinel errors. Callers compare with errors.Is — the wrapping in
// Validate / Apply / VerifyRLS / Remove always uses %w so the chain
// stays intact for the deployment_provision_step status mapping that
// Phase 12e wires.
var (
	// ErrInvalidInput signals a caller-side bug: an unsafe slug, empty
	// admin DSN, etc. Treat as permanent — never retried by the destroy
	// reconciler.
	ErrInvalidInput = errors.New("postgres: invalid input")

	// ErrInvalidName signals a computed DB or role name violates the
	// Postgres identifier alphabet or length limit. Surfaced from the
	// naming helpers before any SQL is issued.
	ErrInvalidName = errors.New("postgres: invalid identifier")

	// ErrDatabaseExists is reserved for the explicit "I expected to
	// create a fresh DB and one already exists" caller scenario. Apply
	// itself is idempotent and does NOT return this — it is returned by
	// the lower-level createDatabase helper when invoked outside the
	// Apply flow (e.g. future force-recreate path).
	ErrDatabaseExists = errors.New("postgres: database already exists")

	// ErrRoleExists mirrors ErrDatabaseExists for the role case.
	ErrRoleExists = errors.New("postgres: role already exists")

	// ErrMigrationFailed wraps any failure from the embedded golang-
	// migrate runner. The wrapped error carries the migration version;
	// ErrMigrationFailed stays as the sentinel so the destroy reconciler
	// can distinguish "migration broke" from "DDL broke" without
	// parsing strings.
	ErrMigrationFailed = errors.New("postgres: data-plane migrations failed")

	// ErrRLSNotEnforced is returned by VerifyRLS when at least one
	// tenant-bound table reports relrowsecurity=false or
	// relforcerowsecurity=false. This is the layer-3 invariant test in
	// production code path, not just in CI — it catches forgotten
	// FORCE clauses in a future migration. The wrapped error names the
	// offending table.
	ErrRLSNotEnforced = errors.New("postgres: RLS not enforced on tenant-bound table")

	// ErrRLSProbeFailed is returned when the role-bound smoke probe
	// (insert under one GUC, attempt to read under another) returns
	// the wrong row count. Distinct from ErrRLSNotEnforced because the
	// remediation is different — RLS may be FORCEd but a policy may be
	// missing or wrong.
	ErrRLSProbeFailed = errors.New("postgres: RLS probe returned unexpected row count")

	// ErrConfirmationRequired guards DROP DATABASE behind an explicit
	// flag on RemoveInput. Returned without touching the cluster when
	// ConfirmDropDatabase=false.
	ErrConfirmationRequired = errors.New("postgres: DROP DATABASE requires explicit confirmation")

	// ErrConnectionsOpen is returned by Remove when DROP DATABASE
	// fails because clients are still connected. The operator must
	// terminate the connections (or wait for them to drain) before
	// retrying.
	ErrConnectionsOpen = errors.New("postgres: cannot drop database while connections are open")
)
