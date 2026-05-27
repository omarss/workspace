package postgres

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strings"

	"github.com/jackc/pgx/v5"
)

// HostAdapter is the production implementation of Adapter. It speaks
// directly to the host Postgres via pgx, using single-connection
// sessions for the privileged DDL (CREATE DATABASE cannot run inside a
// transaction and pgxpool reuses connections in a way that complicates
// the autocommit semantics, so we use pgx.Connect directly).
//
// The adapter is stateless — every method opens its own connection from
// the supplied DSN. This keeps the Phase 12e composite provisioner
// simple (no lifetime management) at the cost of per-Apply connection
// overhead (a few hundred ms; acceptable because provisioning is a
// human-scale operation, not a request-path hot path).
type HostAdapter struct {
	// migrations is the embedded data-plane migration applier. Defaults
	// to the production runner in migrate.go; tests inject a stub.
	migrations migrationsApplier
}

// NewHostAdapter returns the production adapter wired to the embedded
// data-plane migration runner. Phase 12c keeps the constructor free of
// options — every per-call value lives on ApplyInput.
func NewHostAdapter() *HostAdapter {
	return &HostAdapter{migrations: defaultMigrations{}}
}

// Apply implements the orchestration described in the package doc and
// in docs/plans/mvp/13c-postgres-provisioner.md §12c.1.
//
// Step order matters: a database must exist before grants can be issued
// against it; the role must exist before grants can target it; the
// migrations must run as the app role (so table ownership matches the
// security boundary we then enforce). VerifyRLS is intentionally the
// last step so a future migration that forgets ALTER TABLE ... FORCE
// fails the Apply rather than silently weakening isolation.
func (a *HostAdapter) Apply(ctx context.Context, in ApplyInput) (ApplyResult, error) {
	if err := in.Validate(); err != nil {
		return ApplyResult{}, err
	}

	dbName := in.DBName()
	roleName := in.RoleName()

	// Open a control connection against the admin DSN. CREATE DATABASE
	// requires a session not in a transaction and not connected to the
	// target DB; the admin DSN should point at the host's `postgres` or
	// equivalent maintenance database.
	adminConn, err := pgx.Connect(ctx, in.AdminDSN)
	if err != nil {
		return ApplyResult{}, fmt.Errorf("connect admin: %w", err)
	}
	defer func() { _ = adminConn.Close(ctx) }()

	if err := createDatabaseIfMissing(ctx, adminConn, dbName); err != nil {
		return ApplyResult{}, err
	}

	rolePassword, err := generateRolePassword()
	if err != nil {
		return ApplyResult{}, fmt.Errorf("generate password: %w", err)
	}
	if err := createOrRotateRolePassword(ctx, adminConn, roleName, rolePassword); err != nil {
		return ApplyResult{}, err
	}

	if err := setRoleSearchPath(ctx, adminConn, roleName); err != nil {
		return ApplyResult{}, err
	}

	// Grants on the database (CONNECT, schema USAGE, default privileges)
	// must be issued from a session connected to the target DB — schema
	// objects belong to that DB. We open a fresh connection on the
	// admin credentials but with `database=<dbName>` substituted in.
	perDBAdminDSN, err := dsnSwitchDatabase(in.AdminDSN, dbName)
	if err != nil {
		return ApplyResult{}, err
	}
	dbAdminConn, err := pgx.Connect(ctx, perDBAdminDSN)
	if err != nil {
		return ApplyResult{}, fmt.Errorf("connect per-db admin: %w", err)
	}
	defer func() { _ = dbAdminConn.Close(ctx) }()

	if err := grantSchemaAccess(ctx, dbAdminConn, dbName, roleName); err != nil {
		return ApplyResult{}, err
	}

	// Build the per-Deployment DSN that the migrations runner — and
	// later the data-plane pod — will use. The runner expects the role
	// to already have CONNECT + USAGE, which the step above just
	// granted.
	perDeploymentDSN, err := buildDSN(in.AdminDSN, dbName, roleName, rolePassword, in.HostExternal)
	if err != nil {
		return ApplyResult{}, err
	}

	if err := a.migrations.Up(ctx, perDeploymentDSN); err != nil {
		return ApplyResult{}, fmt.Errorf("%w: %w", ErrMigrationFailed, err)
	}

	// Post-migration grant tightening. Phase 10's migration grants
	// SELECT + INSERT on audit_event TO PUBLIC; we narrow PUBLIC ALL
	// and then re-grant only what the app role needs. The order is
	// important: REVOKE before GRANT, otherwise an interleaved
	// connection could see a window with no INSERT permission.
	if err := tightenTableGrants(ctx, dbAdminConn, roleName); err != nil {
		return ApplyResult{}, err
	}

	if err := a.VerifyRLS(ctx, perDeploymentDSN); err != nil {
		return ApplyResult{}, err
	}

	return ApplyResult{
		DBName:           dbName,
		RoleName:         roleName,
		RolePassword:     rolePassword,
		PerDeploymentDSN: perDeploymentDSN,
	}, nil
}

// Remove drops the per-Deployment DB and role. The ConfirmDropDatabase
// flag has already been validated by RemoveInput.Validate, so reaching
// here means the caller affirmatively consented.
//
// Order: DROP DATABASE first (cascades schema objects implicitly), then
// DROP ROLE. We cannot DROP ROLE while owned objects exist, so this
// order is mandatory.
func (a *HostAdapter) Remove(ctx context.Context, in RemoveInput) error {
	if err := in.Validate(); err != nil {
		return err
	}

	adminConn, err := pgx.Connect(ctx, in.AdminDSN)
	if err != nil {
		return fmt.Errorf("connect admin: %w", err)
	}
	defer func() { _ = adminConn.Close(ctx) }()

	dbName := in.DBName()
	roleName := in.RoleName()

	// DROP DATABASE WITH (FORCE) terminates background workers in
	// Postgres 13+. We rely on the operator to terminate user
	// connections beforehand; FORCE handles the autovacuum / replication
	// edge cases.
	dropSQL := fmt.Sprintf(`DROP DATABASE IF EXISTS %s WITH (FORCE)`, quoteIdentifier(dbName))
	if _, err := adminConn.Exec(ctx, dropSQL); err != nil {
		// 55006 = object_in_use. Surface the dedicated sentinel so
		// the operator's runbook knows to terminate connections.
		if isErrCode(err, "55006") {
			return fmt.Errorf("%w: %w", ErrConnectionsOpen, err)
		}
		return fmt.Errorf("drop database %s: %w", dbName, err)
	}

	dropRoleSQL := fmt.Sprintf(`DROP ROLE IF EXISTS %s`, quoteIdentifier(roleName))
	if _, err := adminConn.Exec(ctx, dropRoleSQL); err != nil {
		return fmt.Errorf("drop role %s: %w", roleName, err)
	}
	return nil
}

// createDatabaseIfMissing checks pg_database before issuing CREATE
// DATABASE. CREATE DATABASE has no IF NOT EXISTS form (Postgres rejects
// the syntax), so a presence query is the only idempotent path.
func createDatabaseIfMissing(ctx context.Context, conn *pgx.Conn, dbName string) error {
	var exists bool
	if err := conn.QueryRow(
		ctx,
		`SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = $1)`, dbName,
	).Scan(&exists); err != nil {
		return fmt.Errorf("check pg_database: %w", err)
	}
	if exists {
		return nil
	}
	// ENCODING + LC_* + TEMPLATE pinned for reproducibility across
	// hosts. template0 (not template1) so we get a clean slate even if
	// the host's template1 has been customised.
	stmt := fmt.Sprintf(
		`CREATE DATABASE %s ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0`,
		quoteIdentifier(dbName),
	)
	if _, err := conn.Exec(ctx, stmt); err != nil {
		return fmt.Errorf("create database %s: %w", dbName, err)
	}
	return nil
}

// createOrRotateRolePassword creates the role if missing, otherwise
// ALTER ROLE ... PASSWORD rotates the password in place. The role is
// always NOINHERIT LOGIN — never SUPERUSER, never CREATEDB, never
// CREATEROLE (anti-pattern guard §12c, "NEVER create a role with
// SUPERUSER or CREATEDB").
func createOrRotateRolePassword(ctx context.Context, conn *pgx.Conn, roleName, password string) error {
	var exists bool
	if err := conn.QueryRow(
		ctx,
		`SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = $1)`, roleName,
	).Scan(&exists); err != nil {
		return fmt.Errorf("check pg_roles: %w", err)
	}
	if exists {
		stmt := fmt.Sprintf(
			`ALTER ROLE %s WITH LOGIN NOINHERIT PASSWORD %s`,
			quoteIdentifier(roleName), quoteLiteral(password),
		)
		if _, err := conn.Exec(ctx, stmt); err != nil {
			return fmt.Errorf("alter role %s: %w", roleName, err)
		}
		return nil
	}
	stmt := fmt.Sprintf(
		`CREATE ROLE %s WITH LOGIN NOINHERIT PASSWORD %s`,
		quoteIdentifier(roleName), quoteLiteral(password),
	)
	if _, err := conn.Exec(ctx, stmt); err != nil {
		return fmt.Errorf("create role %s: %w", roleName, err)
	}
	return nil
}

// setRoleSearchPath pins the role's default search_path. Phase 12c sets
// it to `public` because the data-plane migrations create tables in
// `public` (the existing Phase 2-10 SQL); Phase 12e's planned move to a
// dedicated `app` schema will revisit this once the migrations adopt
// `app.*` qualified DDL.
//
// ALTER ROLE ... SET is idempotent: re-issuing with the same value is a
// no-op at the catalog level.
func setRoleSearchPath(ctx context.Context, conn *pgx.Conn, roleName string) error {
	stmt := fmt.Sprintf(`ALTER ROLE %s SET search_path = public`, quoteIdentifier(roleName))
	if _, err := conn.Exec(ctx, stmt); err != nil {
		return fmt.Errorf("alter role search_path: %w", err)
	}
	return nil
}

// grantSchemaAccess issues the per-database grants the migrations need
// to land tables the role can read. Runs inside the target database
// (the caller switched connections); GRANT is naturally idempotent
// in Postgres so re-running is safe.
//
// REVOKE ALL ... FROM PUBLIC is the defense-in-depth measure that
// neutralises the placeholder `GRANT TO PUBLIC` in the existing Phase
// 2-10 migrations. Combined with the dedicated grants on the role, the
// effect is least-privilege.
func grantSchemaAccess(ctx context.Context, conn *pgx.Conn, dbName, roleName string) error {
	stmts := []string{
		// Lock down public schema before granting.
		`REVOKE ALL ON SCHEMA public FROM PUBLIC`,
		fmt.Sprintf(`GRANT CONNECT ON DATABASE %s TO %s`, quoteIdentifier(dbName), quoteIdentifier(roleName)),
		fmt.Sprintf(`GRANT USAGE ON SCHEMA public TO %s`, quoteIdentifier(roleName)),
		fmt.Sprintf(`GRANT CREATE ON SCHEMA public TO %s`, quoteIdentifier(roleName)),
		// Default privileges for objects this role will create during
		// migrations. ALTER DEFAULT PRIVILEGES FOR ROLE <r> grants
		// future <r>-owned tables back to <r> automatically — without
		// this, the migration runner can create tables it cannot then
		// re-grant SELECT/INSERT/UPDATE/DELETE on via the post-migrate
		// tail (because future objects are not yet owned).
		fmt.Sprintf(`ALTER DEFAULT PRIVILEGES FOR ROLE %s IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %s`, quoteIdentifier(roleName), quoteIdentifier(roleName)),
		fmt.Sprintf(`ALTER DEFAULT PRIVILEGES FOR ROLE %s IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO %s`, quoteIdentifier(roleName), quoteIdentifier(roleName)),
	}
	for _, s := range stmts {
		if _, err := conn.Exec(ctx, s); err != nil {
			return fmt.Errorf("grant: %s: %w", s, err)
		}
	}
	return nil
}

// tightenTableGrants is the post-migrate tail. The Phase 2-10
// migrations grant SELECT/INSERT/UPDATE/DELETE on every table TO PUBLIC
// (placeholder convention until Phase 11c — see audit migration
// comment). We now:
//
//  1. REVOKE ALL ... FROM PUBLIC on every table the migrations created
//     in `public`. This relies on the migrations having run as the app
//     role (which they did — the runner uses perDeploymentDSN), so the
//     role retains its owner-grants and PUBLIC loses its placeholder
//     grants.
//  2. Re-tighten audit_event to SELECT + INSERT only on the role
//     (REVOKE UPDATE / DELETE / TRUNCATE). The migration's BEFORE
//     UPDATE / DELETE triggers are belt; the grant is braces.
//
// REVOKE / GRANT in Postgres are not transactional with the user-visible
// query plan, but the planner reloads on the next statement, so the
// gap is microseconds — small enough to ignore for a provisioning
// step that runs once per Deployment.
func tightenTableGrants(ctx context.Context, conn *pgx.Conn, roleName string) error {
	// Discover every table the migrations created in public. We do not
	// hard-code the list here — that would force this adapter to be
	// updated every time a new migration adds a table. Instead we
	// query pg_class.
	rows, err := conn.Query(ctx, `
		SELECT c.relname
		FROM pg_class c
		JOIN pg_namespace n ON n.oid = c.relnamespace
		WHERE n.nspname = 'public'
		  AND c.relkind = 'r'
	`)
	if err != nil {
		return fmt.Errorf("list tables: %w", err)
	}
	defer rows.Close()
	var tables []string
	for rows.Next() {
		var t string
		if err := rows.Scan(&t); err != nil {
			return fmt.Errorf("scan table: %w", err)
		}
		tables = append(tables, t)
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("iterate tables: %w", err)
	}

	for _, t := range tables {
		// PUBLIC was the placeholder grantee; revoke it now that the
		// role-bound grants are in place via ownership.
		stmt := fmt.Sprintf(`REVOKE ALL ON TABLE %s FROM PUBLIC`, quoteIdentifier(t))
		if _, err := conn.Exec(ctx, stmt); err != nil {
			return fmt.Errorf("revoke from public on %s: %w", t, err)
		}
	}

	// audit_event: tighten the role's own grants to SELECT + INSERT.
	// Belt-and-braces with the trigger that the migration installs.
	auditStmts := []string{
		fmt.Sprintf(`REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_event FROM %s`, quoteIdentifier(roleName)),
		fmt.Sprintf(`GRANT SELECT, INSERT ON TABLE audit_event TO %s`, quoteIdentifier(roleName)),
	}
	for _, s := range auditStmts {
		if _, err := conn.Exec(ctx, s); err != nil {
			// audit_event may not exist if a future migration drops
			// it (not our case in Phase 12c, but defensive).
			if isErrCode(err, "42P01") {
				continue
			}
			return fmt.Errorf("audit grant: %w", err)
		}
	}
	return nil
}

// dsnSwitchDatabase returns a new DSN with the database name replaced.
// Used after CREATE DATABASE to connect to the freshly created DB as
// the same admin role for the per-DB grants.
//
// Handles both URL-style (`postgres://user:pass@host:port/db?...`) and
// keyword-value (`host=... dbname=... ...`) DSN forms; pgx accepts both.
func dsnSwitchDatabase(dsn, dbName string) (string, error) {
	if strings.HasPrefix(dsn, "postgres://") || strings.HasPrefix(dsn, "postgresql://") {
		u, err := url.Parse(dsn)
		if err != nil {
			return "", fmt.Errorf("parse admin dsn: %w", err)
		}
		u.Path = "/" + dbName
		return u.String(), nil
	}
	// Keyword-value form. Substitute dbname=, appending if missing.
	parts := strings.Fields(dsn)
	found := false
	for i, p := range parts {
		if strings.HasPrefix(p, "dbname=") {
			parts[i] = "dbname=" + dbName
			found = true
		}
	}
	if !found {
		parts = append(parts, "dbname="+dbName)
	}
	return strings.Join(parts, " "), nil
}

// buildDSN composes the per-Deployment DSN from the admin DSN's host +
// port. The role + password override the admin's credentials; the
// database is the per-Deployment DB. sslmode defaults to whatever the
// admin DSN specifies (or `prefer` if absent — libpq default); the
// caller can override by appending to the admin DSN before passing it in.
//
// hostExternal, when set, overrides the host (used when control-plane
// and data-plane see Postgres at different addresses).
func buildDSN(adminDSN, dbName, roleName, password, hostExternal string) (string, error) {
	// We support only URL-style DSNs for the per-Deployment value. The
	// admin DSN may be keyword-value; in that case we convert.
	var host, port, sslmode string
	if strings.HasPrefix(adminDSN, "postgres://") || strings.HasPrefix(adminDSN, "postgresql://") {
		u, err := url.Parse(adminDSN)
		if err != nil {
			return "", fmt.Errorf("parse admin dsn: %w", err)
		}
		host = u.Hostname()
		port = u.Port()
		sslmode = u.Query().Get("sslmode")
	} else {
		for _, p := range strings.Fields(adminDSN) {
			k, v, ok := strings.Cut(p, "=")
			if !ok {
				continue
			}
			switch k {
			case "host":
				host = v
			case "port":
				port = v
			case "sslmode":
				sslmode = v
			}
		}
	}
	if hostExternal != "" {
		host = hostExternal
	}
	if host == "" {
		host = "localhost"
	}
	if port == "" {
		port = "5432"
	}
	if sslmode == "" {
		// Default to disable for the homelab dev path; production
		// will override via hostExternal + admin DSN's sslmode=verify-full.
		sslmode = "disable"
	}
	u := &url.URL{
		Scheme: "postgres",
		User:   url.UserPassword(roleName, password),
		Host:   host + ":" + port,
		Path:   "/" + dbName,
	}
	q := u.Query()
	q.Set("sslmode", sslmode)
	u.RawQuery = q.Encode()
	return u.String(), nil
}

// isErrCode returns true when the wrapped error is a *pgconn.PgError
// with the given SQLSTATE. Used to distinguish "object in use" from
// generic failures without leaking pgconn into the public API.
func isErrCode(err error, code string) bool {
	type pgErrCoder interface{ SQLState() string }
	var pe pgErrCoder
	if errors.As(err, &pe) {
		return pe.SQLState() == code
	}
	return false
}
