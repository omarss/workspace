//go:build integration

// Integration tests for the Postgres provisioner. These spin up a real
// Postgres container via testcontainers-go and exercise the full Apply
// / VerifyRLS / Remove flow. Run with `make test-int`.
//
// The tests are skip-friendly: if Docker is not available they emit a
// Skip rather than failing, matching the convention of every other
// integration test in this repo (see e.g. internal/dataplane/tenancy/
// repo_pgx_test.go).

package postgres

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	tcpostgres "github.com/testcontainers/testcontainers-go/modules/postgres"
)

// startContainer spins up a one-shot Postgres 16 container and returns
// the superuser admin DSN. Each test gets its own container — we are
// provisioning a fresh DB per Apply, but the container itself has the
// `saas` maintenance DB the adapter connects to first.
func startContainer(t *testing.T) (adminDSN string, terminate func()) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()

	c, err := tcpostgres.Run(
		ctx,
		"postgres:16",
		tcpostgres.WithDatabase("saas"),
		tcpostgres.WithUsername("saas"),
		tcpostgres.WithPassword("saas"),
		tcpostgres.BasicWaitStrategies(),
	)
	if err != nil {
		t.Skipf("docker unavailable: %v", err)
	}
	dsn, err := c.ConnectionString(ctx, "sslmode=disable")
	if err != nil {
		t.Fatalf("conn string: %v", err)
	}
	terminate = func() {
		shutdownCtx, sc := context.WithTimeout(context.Background(), 30*time.Second)
		defer sc()
		_ = c.Terminate(shutdownCtx)
	}
	return dsn, terminate
}

func TestHostAdapterApply_HappyPath(t *testing.T) {
	adminDSN, stop := startContainer(t)
	defer stop()

	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	a := NewHostAdapter()
	in := ApplyInput{
		DeploymentID:    "dep_smoke_happy",
		ProjectSlug:     "smoke",
		EnvironmentSlug: "happy",
		AdminDSN:        adminDSN,
	}
	res, err := a.Apply(ctx, in)
	if err != nil {
		t.Fatalf("Apply: %v", err)
	}
	if res.DBName != "saas_smoke_happy" {
		t.Fatalf("DBName = %q, want saas_smoke_happy", res.DBName)
	}
	if res.RoleName != "saas_smoke_happy_app" {
		t.Fatalf("RoleName = %q, want saas_smoke_happy_app", res.RoleName)
	}
	if len(res.RolePassword) != 40 {
		t.Fatalf("RolePassword len = %d, want 40", len(res.RolePassword))
	}
	if !strings.Contains(res.PerDeploymentDSN, "saas_smoke_happy_app:") {
		t.Fatalf("PerDeploymentDSN does not embed app role: %q", res.PerDeploymentDSN)
	}

	// Verify the DSN is actually usable.
	conn, err := pgx.Connect(ctx, res.PerDeploymentDSN)
	if err != nil {
		t.Fatalf("connect per-deployment dsn: %v", err)
	}
	defer func() { _ = conn.Close(ctx) }()

	var who string
	if err := conn.QueryRow(ctx, `SELECT current_user`).Scan(&who); err != nil {
		t.Fatalf("query current_user: %v", err)
	}
	if who != "saas_smoke_happy_app" {
		t.Fatalf("current_user = %q, want saas_smoke_happy_app", who)
	}

	// The audit_event row count should be zero — the migrations
	// ran but no audit rows were inserted.
	var nAudit int
	// Need a GUC for RLS-bound SELECT; use a fixture id.
	if _, err := conn.Exec(ctx, `SELECT set_config('app.current_tenant_id', 'tenant_post_apply', false)`); err != nil {
		t.Fatalf("set guc: %v", err)
	}
	if err := conn.QueryRow(ctx, `SELECT count(*) FROM audit_event`).Scan(&nAudit); err != nil {
		t.Fatalf("count audit_event: %v", err)
	}
	if nAudit != 0 {
		t.Fatalf("audit_event count = %d under fresh DB, want 0", nAudit)
	}

	// audit_event UPDATE/DELETE must fail (grant tighten + trigger).
	if _, err := conn.Exec(ctx, `UPDATE audit_event SET action = 'tamper'`); err == nil {
		t.Fatalf("UPDATE audit_event succeeded; want permission denied or trigger error")
	}
	if _, err := conn.Exec(ctx, `DELETE FROM audit_event`); err == nil {
		t.Fatalf("DELETE audit_event succeeded; want permission denied or trigger error")
	}
}

func TestHostAdapterApply_Idempotent(t *testing.T) {
	adminDSN, stop := startContainer(t)
	defer stop()

	ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
	defer cancel()

	a := NewHostAdapter()
	in := ApplyInput{
		DeploymentID:    "dep_smoke_idem",
		ProjectSlug:     "smoke",
		EnvironmentSlug: "idem",
		AdminDSN:        adminDSN,
	}
	res1, err := a.Apply(ctx, in)
	if err != nil {
		t.Fatalf("Apply (first): %v", err)
	}
	// Second Apply rotates the password but leaves the DB + role alone.
	res2, err := a.Apply(ctx, in)
	if err != nil {
		t.Fatalf("Apply (second): %v", err)
	}
	if res1.RolePassword == res2.RolePassword {
		t.Fatalf("expected password rotation on re-Apply, got same password")
	}
	// The new password is usable.
	conn, err := pgx.Connect(ctx, res2.PerDeploymentDSN)
	if err != nil {
		t.Fatalf("connect with rotated password: %v", err)
	}
	_ = conn.Close(ctx)
	// The old password is no longer usable.
	if _, err := pgx.Connect(ctx, res1.PerDeploymentDSN); err == nil {
		t.Fatalf("connect with rotated-away password succeeded; want failure")
	}
}

func TestHostAdapterVerifyRLS_BitesAcrossTenants(t *testing.T) {
	adminDSN, stop := startContainer(t)
	defer stop()

	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	a := NewHostAdapter()
	res, err := a.Apply(ctx, ApplyInput{
		DeploymentID:    "dep_smoke_rls",
		ProjectSlug:     "smoke",
		EnvironmentSlug: "rls",
		AdminDSN:        adminDSN,
	})
	if err != nil {
		t.Fatalf("Apply: %v", err)
	}

	// Direct RLS cross-tenant probe, separate from the in-Apply
	// VerifyRLS that just succeeded.
	conn, err := pgx.Connect(ctx, res.PerDeploymentDSN)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer func() { _ = conn.Close(ctx) }()

	// Insert under tenant_X.
	if _, err := conn.Exec(ctx, `SELECT set_config('app.current_tenant_id', 'tenant_X', false)`); err != nil {
		t.Fatalf("set guc X: %v", err)
	}
	if _, err := conn.Exec(ctx, `INSERT INTO tenant (id, slug, name) VALUES ('tenant_X', 'x', 'X')`); err != nil {
		t.Fatalf("insert tenant X: %v", err)
	}
	var nUnderX int
	if err := conn.QueryRow(ctx, `SELECT count(*) FROM tenant`).Scan(&nUnderX); err != nil {
		t.Fatalf("count under X: %v", err)
	}
	if nUnderX != 1 {
		t.Fatalf("count under X = %d, want 1", nUnderX)
	}

	// Switch to tenant_Y; should see zero rows.
	if _, err := conn.Exec(ctx, `SELECT set_config('app.current_tenant_id', 'tenant_Y', false)`); err != nil {
		t.Fatalf("set guc Y: %v", err)
	}
	var nUnderY int
	if err := conn.QueryRow(ctx, `SELECT count(*) FROM tenant`).Scan(&nUnderY); err != nil {
		t.Fatalf("count under Y: %v", err)
	}
	if nUnderY != 0 {
		t.Fatalf("count under Y = %d, want 0 (RLS did not bite)", nUnderY)
	}
}

func TestHostAdapterRemove_RequiresConfirmation(t *testing.T) {
	adminDSN, stop := startContainer(t)
	defer stop()

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	a := NewHostAdapter()
	_, err := a.Apply(ctx, ApplyInput{
		DeploymentID:    "dep_smoke_rm",
		ProjectSlug:     "smoke",
		EnvironmentSlug: "rm",
		AdminDSN:        adminDSN,
	})
	if err != nil {
		t.Fatalf("Apply: %v", err)
	}

	// Remove without the flag: refused.
	err = a.Remove(ctx, RemoveInput{
		DeploymentID:    "dep_smoke_rm",
		ProjectSlug:     "smoke",
		EnvironmentSlug: "rm",
		AdminDSN:        adminDSN,
	})
	if !errors.Is(err, ErrConfirmationRequired) {
		t.Fatalf("Remove without flag = %v, want ErrConfirmationRequired", err)
	}

	// Remove with the flag: succeeds.
	err = a.Remove(ctx, RemoveInput{
		DeploymentID:        "dep_smoke_rm",
		ProjectSlug:         "smoke",
		EnvironmentSlug:     "rm",
		AdminDSN:            adminDSN,
		ConfirmDropDatabase: true,
	})
	if err != nil {
		t.Fatalf("Remove with flag: %v", err)
	}

	// Verify DB is gone.
	conn, err := pgx.Connect(ctx, adminDSN)
	if err != nil {
		t.Fatalf("admin connect: %v", err)
	}
	defer func() { _ = conn.Close(ctx) }()
	var exists bool
	if err := conn.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'saas_smoke_rm')`).Scan(&exists); err != nil {
		t.Fatalf("check pg_database: %v", err)
	}
	if exists {
		t.Fatalf("DB saas_smoke_rm still exists after Remove")
	}
	var roleExists bool
	if err := conn.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'saas_smoke_rm_app')`).Scan(&roleExists); err != nil {
		t.Fatalf("check pg_roles: %v", err)
	}
	if roleExists {
		t.Fatalf("role saas_smoke_rm_app still exists after Remove")
	}
}
