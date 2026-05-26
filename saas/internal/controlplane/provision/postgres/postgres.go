// Package postgres is the control-plane's host-Postgres adapter. For each
// Deployment it creates a dedicated database (saas_<project>_<env>) and
// least-privilege app role (saas_<project>_<env>_app), grants schema and
// table privileges, applies the embedded data-plane migrations against the
// new database, and verifies that every tenant-bound table is RLS-FORCEd
// before declaring success.
//
// Phase 12c ships the adapter in isolation — it is NOT wired into the
// LocalProvisioner from Phase 11. Phase 12e composes the full §6.2
// 13-step provisioning sequence with this adapter alongside the k3s,
// nginx, and OpenBao adapters. The only callers in Phase 12c are:
//
//   - The integration tests in this package (testcontainers-postgres).
//   - The `saasctl debug postgres apply <dep_id>` CP-7 verification
//     command (build-tagged `!prod`).
//
// Password handling: Phase 12c does NOT persist the generated app-role
// password anywhere. ApplyResult returns it once; the operator captures
// it for the CP-7 smoke procedure. Phase 12d wires OpenBao KV storage and
// Phase 12e composes the full sequence with KV-stored passwords. Keeping
// password persistence out of this phase means the adapter has zero
// dependency on OpenBao and can be reviewed in isolation.
//
// See docs/plans/mvp/13c-postgres-provisioner.md and AGENTS.md §6.1, §6.2,
// §18.1 layer 3 (RLS) for the operator-facing contract.
package postgres

import (
	"context"
	"fmt"
)

// Adapter is the contract the composite provisioner (Phase 12e) calls.
// Kept narrow on purpose — provisioning, removal, and the RLS invariant
// probe. The interface lives here (not in `internal/controlplane/
// deployments`) so other packages can fake-implement it without pulling
// in pgx + golang-migrate.
type Adapter interface {
	// Apply provisions the per-Deployment database and role:
	//   1. CREATE DATABASE saas_<project>_<env> if missing.
	//   2. CREATE ROLE saas_<project>_<env>_app NOINHERIT LOGIN, or
	//      rotate the password if the role already exists.
	//   3. Grant CONNECT + schema USAGE; set search_path on the role.
	//   4. Apply the embedded data-plane migrations against the new DB.
	//   5. Tighten table-level grants (audit_event = SELECT + INSERT only).
	//   6. Verify FORCE RLS is enforced on every tenant-bound table.
	//
	// Each step is idempotent: re-running Apply on an already-provisioned
	// Deployment rotates the password and re-checks invariants without
	// touching schema state. Returns the freshly generated app-role
	// password ONCE via ApplyResult — the caller is responsible for
	// capturing it. Phase 12c does not persist the password.
	Apply(ctx context.Context, in ApplyInput) (ApplyResult, error)

	// Remove drops the per-Deployment database and role. Requires
	// RemoveInput.ConfirmDropDatabase=true; the adapter refuses to
	// execute DROP DATABASE without explicit confirmation. The caller
	// must terminate any open connections to the database before calling
	// Remove — Postgres refuses DROP DATABASE while connections exist.
	Remove(ctx context.Context, in RemoveInput) error

	// VerifyRLS runs the read-only RLS invariant probe against the
	// per-Deployment database. Exposed separately from Apply so the
	// operator (via `saasctl debug postgres verify`) can re-check the
	// invariant on an existing deployment without re-running migrations.
	// Caller-supplied DSN must point at the per-Deployment DB; the
	// adapter does NOT reconstruct it from naming alone.
	VerifyRLS(ctx context.Context, perDeploymentDSN string) error
}

// ApplyInput is the data Apply needs. Caller (Phase 12e or saasctl debug)
// supplies the slugs + admin DSN; the adapter computes DBName / RoleName
// via naming.go.
type ApplyInput struct {
	// DeploymentID is the `dep_<ulid>` identifier. Used in error messages
	// and the RLS smoke tenant fixture; NOT used in DB / role naming
	// (those are slug-derived so they remain stable across deployment
	// recreations within the same project + environment).
	DeploymentID string

	// ProjectSlug + EnvironmentSlug feed the DB and role name. Must be
	// DNS-safe per AGENTS.md §6.2 (the control-plane enforces this on
	// the deployment row before reaching the adapter); double-validated
	// here against a stricter Postgres-identifier alphabet.
	ProjectSlug     string
	EnvironmentSlug string

	// AdminDSN is the superuser-equivalent DSN the adapter uses for
	// CREATE DATABASE / CREATE ROLE. Read from OpenBao KV by the caller
	// (Phase 12d/12e); in Phase 12c the operator passes it directly via
	// `saasctl debug postgres apply --admin-dsn ...`.
	//
	// The DSN must NOT specify a database — the adapter switches to the
	// per-Deployment DB itself after CREATE DATABASE.
	AdminDSN string

	// HostExternal optionally overrides the host:port the adapter
	// embeds in the returned per-Deployment DSN. Defaults to the host
	// parsed from AdminDSN. Used when the control-plane sees Postgres
	// at one address and the data-plane pod sees it at another.
	HostExternal string

	// RotatePassword forces password rotation when the role already
	// exists. The default is to always issue a fresh password on Apply
	// (idempotent rotation is the security-positive choice); this flag
	// is reserved for future use where idempotent re-Apply must not
	// invalidate the previous password until the rotation handshake is
	// staged. Phase 12c always rotates.
	RotatePassword bool
}

// Validate enforces the Phase 12c input contract.
//
// Slug validation is strict because the values end up concatenated into
// the DB name and role name (which are DDL identifiers, not parameters).
// We refuse anything outside [a-z0-9_], and we enforce the combined name
// length against Postgres' NAMEDATALEN-1 = 63 limit.
func (in ApplyInput) Validate() error {
	if in.DeploymentID == "" {
		return fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}
	if !isSafeDeploymentID(in.DeploymentID) {
		return fmt.Errorf("%w: deployment_id %q has unsafe characters", ErrInvalidInput, in.DeploymentID)
	}
	if err := validateSlug("project_slug", in.ProjectSlug); err != nil {
		return err
	}
	if err := validateSlug("environment_slug", in.EnvironmentSlug); err != nil {
		return err
	}
	if in.AdminDSN == "" {
		return fmt.Errorf("%w: admin_dsn empty", ErrInvalidInput)
	}
	// Pre-compute the names so length validation surfaces at Validate
	// time, not buried inside the first DDL statement.
	if _, err := buildDBName(in.ProjectSlug, in.EnvironmentSlug); err != nil {
		return err
	}
	if _, err := buildRoleName(in.ProjectSlug, in.EnvironmentSlug); err != nil {
		return err
	}
	return nil
}

// DBName returns the per-Deployment database name. Stable across calls;
// failures land in Validate, not here.
func (in ApplyInput) DBName() string {
	n, _ := buildDBName(in.ProjectSlug, in.EnvironmentSlug)
	return n
}

// RoleName returns the per-Deployment app-role name. Stable across calls.
func (in ApplyInput) RoleName() string {
	n, _ := buildRoleName(in.ProjectSlug, in.EnvironmentSlug)
	return n
}

// ApplyResult is what Apply returns on success. The role password is the
// only value the caller MUST capture immediately — Phase 12c persists
// nothing.
type ApplyResult struct {
	// DBName is the provisioned database (saas_<project>_<env>).
	DBName string

	// RoleName is the provisioned app role (saas_<project>_<env>_app).
	RoleName string

	// RolePassword is the freshly generated (or rotated) password for
	// the app role. Returned ONCE. Phase 12c does NOT store it; the
	// caller must capture this value before the function return is
	// dropped. Phase 12d wires KV storage; Phase 12e composes.
	RolePassword string

	// PerDeploymentDSN is the assembled connection string the data-plane
	// pod would use: role + password + host + DB + sslmode. Includes
	// the search_path bias (public for Phase 12c — the dedicated `app`
	// schema is a Phase 12e move per the plan §12c.3 notes).
	PerDeploymentDSN string
}

// RemoveInput is what Remove takes. The ConfirmDropDatabase flag is
// REQUIRED because DROP DATABASE is destructive — passing the flag is
// the operator's affirmative consent.
type RemoveInput struct {
	DeploymentID    string
	ProjectSlug     string
	EnvironmentSlug string
	AdminDSN        string

	// ConfirmDropDatabase MUST be true for Remove to execute. The
	// adapter returns ErrConfirmationRequired otherwise. Defense in
	// depth against accidental cluster-wide destruction (saasctl debug
	// also gates this behind a CLI flag with a 5-second countdown).
	ConfirmDropDatabase bool
}

// Validate enforces the destroy contract.
func (in RemoveInput) Validate() error {
	if in.DeploymentID == "" {
		return fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}
	if !isSafeDeploymentID(in.DeploymentID) {
		return fmt.Errorf("%w: deployment_id %q has unsafe characters", ErrInvalidInput, in.DeploymentID)
	}
	if err := validateSlug("project_slug", in.ProjectSlug); err != nil {
		return err
	}
	if err := validateSlug("environment_slug", in.EnvironmentSlug); err != nil {
		return err
	}
	if in.AdminDSN == "" {
		return fmt.Errorf("%w: admin_dsn empty", ErrInvalidInput)
	}
	if !in.ConfirmDropDatabase {
		return ErrConfirmationRequired
	}
	if _, err := buildDBName(in.ProjectSlug, in.EnvironmentSlug); err != nil {
		return err
	}
	if _, err := buildRoleName(in.ProjectSlug, in.EnvironmentSlug); err != nil {
		return err
	}
	return nil
}

// DBName mirrors ApplyInput.DBName.
func (in RemoveInput) DBName() string {
	n, _ := buildDBName(in.ProjectSlug, in.EnvironmentSlug)
	return n
}

// RoleName mirrors ApplyInput.RoleName.
func (in RemoveInput) RoleName() string {
	n, _ := buildRoleName(in.ProjectSlug, in.EnvironmentSlug)
	return n
}

// isSafeDeploymentID restricts deployment IDs to the same alphabet the
// other adapters accept (ULID + optional `dep_` prefix). The value
// surfaces in RLS smoke fixtures and error messages.
func isSafeDeploymentID(s string) bool {
	if s == "" || len(s) > 64 {
		return false
	}
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z':
		case r >= 'A' && r <= 'Z':
		case r >= '0' && r <= '9':
		case r == '_' || r == '-':
		default:
			return false
		}
	}
	return true
}
