//go:build integration

package tenancy_test

import (
	"context"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	tcpostgres "github.com/testcontainers/testcontainers-go/modules/postgres"

	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
	"github.com/omarss/saas/internal/dataplane/tenancy"
)

// applyMigrations executes every migrations/dataplane/*.up.sql file once,
// in file-name order. We deliberately avoid golang-migrate here so the
// integration test exercises the same SQL that the runner applies in prod.
func applyMigrations(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	root := findRepoRoot(t)
	dir := filepath.Join(root, "migrations", "dataplane")
	files := []string{}
	if err := filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !d.IsDir() && strings.HasSuffix(p, ".up.sql") {
			files = append(files, p)
		}
		return nil
	}); err != nil {
		t.Fatalf("walk migrations: %v", err)
	}
	for _, f := range files {
		sql, err := os.ReadFile(f)
		if err != nil {
			t.Fatalf("read %s: %v", f, err)
		}
		if _, err := pool.Exec(ctx, string(sql)); err != nil {
			t.Fatalf("exec %s: %v", filepath.Base(f), err)
		}
	}
}

// findRepoRoot walks upward from CWD until it finds go.mod.
func findRepoRoot(t *testing.T) string {
	t.Helper()
	wd, _ := os.Getwd()
	dir := wd
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatalf("could not find go.mod from %s", wd)
		}
		dir = parent
	}
}

// startPostgres spins up an ephemeral Postgres container via testcontainers-go.
// Each integration test gets its own container so RLS GUCs don't leak.
func startPostgres(t *testing.T) (*pgxpool.Pool, func()) {
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
	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatalf("pool: %v", err)
	}
	applyMigrations(t, context.Background(), pool)

	cleanup := func() {
		pool.Close()
		shutdownCtx, sc := context.WithTimeout(context.Background(), 30*time.Second)
		defer sc()
		_ = c.Terminate(shutdownCtx)
	}
	return pool, cleanup
}

// withTenantGUC sets the request-bound GUC on a dedicated connection. The
// repository's caller normally relies on the pool's PrepareConn hook for this;
// the integration tests bypass the hook so they can verify both code paths.
func withTenantGUC(t *testing.T, ctx context.Context, pool *pgxpool.Pool, tenantID string) (*pgx.Conn, func()) {
	t.Helper()
	conn, err := pool.Acquire(ctx)
	if err != nil {
		t.Fatalf("acquire: %v", err)
	}
	if _, err := conn.Exec(ctx, "SELECT set_config('app.current_tenant_id', $1, false)", tenantID); err != nil {
		t.Fatalf("set_config: %v", err)
	}
	return conn.Conn(), func() { conn.Release() }
}

func TestRepoPgx_RoundTrip(t *testing.T) {
	pool, cleanup := startPostgres(t)
	defer cleanup()
	ctx := context.Background()

	conn, release := withTenantGUC(t, ctx, pool, "")
	defer release()
	q := db.New(conn)
	repo := tenancy.NewPgxRepository(q)

	t1, err := repo.Create(ctx, tenancy.Tenant{
		ID:     "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA",
		Slug:   "acme",
		Name:   "Acme Inc",
		Status: tenancy.StatusActive,
		RowSeq: 1,
	})
	if err != nil {
		t.Fatalf("Create: %v", err)
	}

	// RLS denies cross-tenant SELECT.
	if _, err := repo.Get(ctx, t1.ID); !errors.Is(err, tenancy.ErrNotFound) {
		t.Fatalf("RLS should hide tenant when GUC unset, got %v", err)
	}

	// Switch GUC to t1.ID — Get should now succeed.
	if _, err := conn.Exec(ctx, "SELECT set_config('app.current_tenant_id', $1, false)", t1.ID); err != nil {
		t.Fatalf("set_config: %v", err)
	}
	got, err := repo.Get(ctx, t1.ID)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if got.Slug != "acme" || got.RowSeq != 1 {
		t.Fatalf("unexpected: %+v", got)
	}

	// Update bumps row_seq and updated_at.
	newName := "Renamed"
	updated, err := repo.Update(ctx, t1.ID, 1, tenancy.UpdatePatch{Name: &newName})
	if err != nil {
		t.Fatalf("Update: %v", err)
	}
	if updated.RowSeq != 2 || updated.Name != "Renamed" {
		t.Fatalf("expected row_seq=2 Renamed, got %+v", updated)
	}
	if !updated.UpdatedAt.After(got.UpdatedAt) {
		t.Fatalf("updated_at did not advance: before=%v after=%v", got.UpdatedAt, updated.UpdatedAt)
	}

	// Stale ETag mismatches.
	if _, err := repo.Update(ctx, t1.ID, 1, tenancy.UpdatePatch{Name: &newName}); !errors.Is(err, tenancy.ErrETagMismatch) {
		t.Fatalf("expected ErrETagMismatch, got %v", err)
	}

	// Soft-delete flips status + deleted_at.
	deleted, err := repo.SoftDelete(ctx, t1.ID, 2)
	if err != nil {
		t.Fatalf("SoftDelete: %v", err)
	}
	if deleted.Status != tenancy.StatusDeleted || deleted.DeletedAt == nil {
		t.Fatalf("expected status=deleted + deleted_at set, got %+v", deleted)
	}
	// Re-Get must now return NotFound.
	if _, err := repo.Get(ctx, t1.ID); !errors.Is(err, tenancy.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestRepoPgx_UniqueSlug(t *testing.T) {
	pool, cleanup := startPostgres(t)
	defer cleanup()
	ctx := context.Background()
	conn, release := withTenantGUC(t, ctx, pool, "")
	defer release()
	repo := tenancy.NewPgxRepository(db.New(conn))

	a, err := repo.Create(ctx, tenancy.Tenant{
		ID: "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA", Slug: "acme", Name: "A",
		Status: tenancy.StatusActive, RowSeq: 1,
	})
	if err != nil {
		t.Fatalf("first Create: %v", err)
	}
	_ = a
	_, err = repo.Create(ctx, tenancy.Tenant{
		ID: "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB", Slug: "acme", Name: "B",
		Status: tenancy.StatusActive, RowSeq: 1,
	})
	if !errors.Is(err, tenancy.ErrSlugTaken) {
		t.Fatalf("expected ErrSlugTaken, got %v", err)
	}
}

func TestRepoPgx_MetadataMarshalled(t *testing.T) {
	pool, cleanup := startPostgres(t)
	defer cleanup()
	ctx := context.Background()
	conn, release := withTenantGUC(t, ctx, pool, "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA")
	defer release()
	repo := tenancy.NewPgxRepository(db.New(conn))

	created, err := repo.Create(ctx, tenancy.Tenant{
		ID: "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA", Slug: "acme", Name: "A",
		Status: tenancy.StatusActive, RowSeq: 1,
		Metadata: map[string]string{"region": "ksa"},
	})
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	// Round-trip the metadata.
	got, err := repo.Get(ctx, created.ID)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if got.Metadata["region"] != "ksa" {
		t.Fatalf("metadata lost: %#v", got.Metadata)
	}
	// Confirm the raw column is jsonb (sanity check the trigger didn't drop it).
	var raw []byte
	if err := conn.QueryRow(ctx, "SELECT metadata FROM tenant WHERE id=$1", created.ID).Scan(&raw); err != nil {
		t.Fatalf("raw select: %v", err)
	}
	var m map[string]string
	if err := json.Unmarshal(raw, &m); err != nil || m["region"] != "ksa" {
		t.Fatalf("raw metadata: %s", raw)
	}
}
