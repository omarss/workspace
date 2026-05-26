package postgres

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// tenantBoundTables lists every per-Deployment table whose RLS posture
// the adapter verifies. Synced manually against the
// migrations/dataplane/*.up.sql files: every ALTER TABLE ... ENABLE +
// FORCE ROW LEVEL SECURITY pair lives in this list.
//
// Excluded on purpose:
//
//   - outbox_event: published cluster-wide by the publisher with a
//     bypass connection; no policy attaches.
//   - permission: global catalog, intentionally readable by all
//     tenants (the migrations grant SELECT to PUBLIC).
//   - casbin_rule: governed by the casbin adapter's own validation,
//     not by the RLS layer. Phase 12c does not verify it.
//   - notification_attempt: lives under notification_workflow; the
//     workflow row's RLS gates the chain. Adding it here would force
//     a migration revisit which is out of scope for 12c.
//   - schema_bootstrap_dataplane: bootstrap marker; not tenant-scoped.
//
// If a future migration adds a tenant-bound table, this list must be
// updated and the integration test in postgres_integration_test.go
// re-run — the failure mode is loud (ErrRLSNotEnforced) at provision
// time, not silent at runtime.
var tenantBoundTables = []string{
	"tenant",
	"idempotency_record",
	"platform_user",
	"identity_provider_mapping",
	"social_login_state",
	"notification_channel",
	"notification_workflow",
	"notification",
	"organization",
	"member",
	"invitation",
	"role",
	"member_role",
	"api_key",
	"audit_event",
}

// VerifyRLS implements Adapter.VerifyRLS. Read-only: opens a connection
// to the per-Deployment DB as the app role and runs three checks.
//
//  1. pg_class invariant: every table in tenantBoundTables has
//     relrowsecurity = true AND relforcerowsecurity = true.
//  2. Insert two rows under tenant fixture A, switch GUC to fixture B,
//     assert SELECT returns 0 rows (RLS bites).
//  3. Switch back to fixture A, assert SELECT returns the inserted
//     rows (RLS does not over-filter).
//
// Cleans up the fixtures before returning. Failure leaves the rows in
// place — the next Apply or a manual cleanup must handle them. We
// accept this tradeoff because the alternative (a cleanup transaction
// that survives an aborted probe) complicates the error handling for
// little gain.
func (a *HostAdapter) VerifyRLS(ctx context.Context, perDeploymentDSN string) error {
	conn, err := pgx.Connect(ctx, perDeploymentDSN)
	if err != nil {
		return fmt.Errorf("connect per-deployment: %w", err)
	}
	defer func() { _ = conn.Close(ctx) }()

	if err := verifyRLSFlags(ctx, conn); err != nil {
		return err
	}
	return verifyRLSProbe(ctx, conn)
}

// verifyRLSFlags reads pg_class for every name in tenantBoundTables and
// asserts both flags are true. We query all rows at once (single
// round-trip) rather than one per table — the table count is small
// enough that the difference is negligible but the single-query form
// makes the failure message easier to read (lists every offender).
func verifyRLSFlags(ctx context.Context, conn *pgx.Conn) error {
	rows, err := conn.Query(ctx, `
		SELECT c.relname,
		       c.relrowsecurity,
		       c.relforcerowsecurity
		FROM pg_class c
		JOIN pg_namespace n ON n.oid = c.relnamespace
		WHERE n.nspname = 'public'
		  AND c.relkind = 'r'
		  AND c.relname = ANY($1)
		ORDER BY c.relname
	`, tenantBoundTables)
	if err != nil {
		return fmt.Errorf("query pg_class: %w", err)
	}
	defer rows.Close()

	seen := make(map[string]bool, len(tenantBoundTables))
	for rows.Next() {
		var name string
		var enabled, forced bool
		if err := rows.Scan(&name, &enabled, &forced); err != nil {
			return fmt.Errorf("scan pg_class row: %w", err)
		}
		seen[name] = true
		if !enabled || !forced {
			return fmt.Errorf("%w: %s (enabled=%t, forced=%t)",
				ErrRLSNotEnforced, name, enabled, forced)
		}
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("iterate pg_class rows: %w", err)
	}

	// A missing table is also a failure — the migrations did not land
	// the expected schema. Surface it via the same sentinel so callers
	// have one branch to handle.
	for _, t := range tenantBoundTables {
		if !seen[t] {
			return fmt.Errorf("%w: %s (table missing — migrations incomplete?)", ErrRLSNotEnforced, t)
		}
	}
	return nil
}

// verifyRLSProbe runs the role-bound smoke probe. Uses two fixture
// tenant IDs (tenant_provision_smoke_a / _b) so the probe is
// idempotent across re-Applies — ON CONFLICT DO NOTHING on the insert,
// DELETE on the cleanup.
//
// All statements run inside a single transaction so the SET LOCAL
// GUCs are scoped tightly. Postgres' SET LOCAL is transaction-scoped
// and is the only safe way to set RLS GUCs without leaking state to
// a future pool acquirer.
func verifyRLSProbe(ctx context.Context, conn *pgx.Conn) error {
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return fmt.Errorf("begin probe tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }() // safe even after commit

	const (
		tenantA = "tenant_provision_smoke_a"
		tenantB = "tenant_provision_smoke_b"
	)

	// Insert two rows under fixture A.
	if _, err := tx.Exec(ctx,
		`SELECT set_config('app.current_tenant_id', $1, true)`, tenantA,
	); err != nil {
		return fmt.Errorf("set guc A: %w", err)
	}
	for _, slug := range []string{"smoke_a_1", "smoke_a_2"} {
		// `tenant` table doubles as the tenant catalog AND the
		// RLS-bound payload. Insert rows where id matches the GUC
		// so the policy permits both INSERT and subsequent SELECT.
		if _, err := tx.Exec(ctx,
			`INSERT INTO tenant (id, slug, name)
			 VALUES ($1, $2, $2)
			 ON CONFLICT (id) DO NOTHING`,
			tenantA, slug,
		); err != nil {
			return fmt.Errorf("insert probe row: %w", err)
		}
	}

	// Read under fixture A — expect exactly the row we inserted (the
	// `tenant` table is keyed by id, so the two inserts collapse onto
	// one row due to ON CONFLICT — that's fine, we just need >0).
	var nA int
	if err := tx.QueryRow(ctx, `SELECT count(*) FROM tenant`).Scan(&nA); err != nil {
		return fmt.Errorf("count under A: %w", err)
	}
	if nA == 0 {
		return fmt.Errorf("%w: count=0 under tenant A (RLS over-filters)", ErrRLSProbeFailed)
	}

	// Switch to fixture B; expect 0 rows.
	if _, err := tx.Exec(ctx,
		`SELECT set_config('app.current_tenant_id', $1, true)`, tenantB,
	); err != nil {
		return fmt.Errorf("set guc B: %w", err)
	}
	var nB int
	if err := tx.QueryRow(ctx, `SELECT count(*) FROM tenant`).Scan(&nB); err != nil {
		return fmt.Errorf("count under B: %w", err)
	}
	if nB != 0 {
		return fmt.Errorf("%w: count=%d under tenant B (RLS does not bite)", ErrRLSProbeFailed, nB)
	}

	// Cleanup: back to A and delete. Important to run before commit
	// so the fixtures do not persist beyond the probe.
	if _, err := tx.Exec(ctx,
		`SELECT set_config('app.current_tenant_id', $1, true)`, tenantA,
	); err != nil {
		return fmt.Errorf("set guc A for cleanup: %w", err)
	}
	if _, err := tx.Exec(ctx, `DELETE FROM tenant WHERE id = $1`, tenantA); err != nil {
		return fmt.Errorf("cleanup probe rows: %w", err)
	}

	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("commit probe: %w", err)
	}
	return nil
}
