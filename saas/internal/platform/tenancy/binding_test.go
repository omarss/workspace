//go:build integration

// Package tenancy_test exercises BindOnAcquire end-to-end against a real
// Postgres connection. The hook emits SELECT set_config(...) on every pool
// acquisition; verifying the GUC is observable via current_setting() is the
// only way to catch silent-no-op regressions where the hook gets unwired in
// pgxpool.NewPool.
//
// Lives under `//go:build integration` because it needs a Docker daemon to
// spin up testcontainers-postgres. The Phase 3 anti-pattern guards forbid
// pretending we can mock pgx.Conn at this layer — the GUC machinery IS the
// surface under test.
package tenancy_test

import (
	"context"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	tcpostgres "github.com/testcontainers/testcontainers-go/modules/postgres"

	"github.com/omarss/saas/internal/platform/auth"
	platformtenancy "github.com/omarss/saas/internal/platform/tenancy"
)

// startPG boots an ephemeral Postgres and returns a pool whose PrepareConn
// hook is the function under test. Each test gets its own container so GUC
// state from prior tests cannot leak — pgx pools persist session state until
// the connection is closed or PrepareConn re-runs.
func startPG(t *testing.T) (*pgxpool.Pool, func()) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	c, err := tcpostgres.Run(
		ctx, "postgres:16",
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
		t.Fatalf("dsn: %v", err)
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatalf("parse config: %v", err)
	}
	// Wire the function under test as the PrepareConn hook. Without this,
	// the GUC is never populated and current_setting() returns empty.
	cfg.PrepareConn = platformtenancy.BindOnAcquire
	// One connection only — guarantees a tenant-switch test does not
	// accidentally get a fresh connection that satisfies the assertion for
	// the wrong reason.
	cfg.MaxConns = 1
	cfg.MinConns = 1

	pool, err := pgxpool.NewWithConfig(context.Background(), cfg)
	if err != nil {
		t.Fatalf("pool: %v", err)
	}
	cleanup := func() {
		pool.Close()
		shutdownCtx, sc := context.WithTimeout(context.Background(), 30*time.Second)
		defer sc()
		_ = c.Terminate(shutdownCtx)
	}
	return pool, cleanup
}

// readGUC returns the value of app.current_tenant_id on the conn currently
// reserved by the supplied context. Uses current_setting with missing_ok=true
// so an unset GUC returns "" rather than an error — that is the exact "safer
// failure mode" the binding contract promises.
func readGUC(ctx context.Context, t *testing.T, pool *pgxpool.Pool) string {
	t.Helper()
	conn, err := pool.Acquire(ctx)
	if err != nil {
		t.Fatalf("acquire: %v", err)
	}
	defer conn.Release()
	var got string
	if err := conn.QueryRow(ctx, "SELECT current_setting('app.current_tenant_id', true)").Scan(&got); err != nil {
		t.Fatalf("read GUC: %v", err)
	}
	return got
}

func TestBindOnAcquire_SetsGUCFromContext(t *testing.T) {
	pool, cleanup := startPG(t)
	defer cleanup()

	ctx := auth.ContextWithTenant(context.Background(), "ten_alpha")
	if got := readGUC(ctx, t, pool); got != "ten_alpha" {
		t.Fatalf("GUC = %q, want %q", got, "ten_alpha")
	}
}

func TestBindOnAcquire_NoTenantInContext_SetsEmpty(t *testing.T) {
	pool, cleanup := startPG(t)
	defer cleanup()

	// Context.Background() carries no tenant. The hook MUST still run and
	// MUST set the GUC to the empty string — this is the documented safer
	// failure mode (RLS returns zero rows rather than leaking the previous
	// caller's tenant).
	if got := readGUC(context.Background(), t, pool); got != "" {
		t.Fatalf("GUC = %q, want empty string", got)
	}
}

func TestBindOnAcquire_TenantSwitch_ResetsGUC(t *testing.T) {
	pool, cleanup := startPG(t)
	defer cleanup()

	// First acquisition with tenant alpha — proves the GUC binds correctly.
	ctxAlpha := auth.ContextWithTenant(context.Background(), "ten_alpha")
	if got := readGUC(ctxAlpha, t, pool); got != "ten_alpha" {
		t.Fatalf("first GUC = %q, want ten_alpha", got)
	}

	// Pool is sized MaxConns=1 so the next Acquire reuses the same physical
	// connection. The hook must re-run and overwrite the previous tenant's
	// session-scoped GUC — otherwise we'd leak ten_alpha's identity into
	// ten_beta's request.
	ctxBeta := auth.ContextWithTenant(context.Background(), "ten_beta")
	if got := readGUC(ctxBeta, t, pool); got != "ten_beta" {
		t.Fatalf("after switch GUC = %q, want ten_beta (stale alpha = isolation breach)", got)
	}
}
