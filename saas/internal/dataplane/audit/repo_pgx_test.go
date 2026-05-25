//go:build integration

package audit_test

import (
	"context"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	tcpostgres "github.com/testcontainers/testcontainers-go/modules/postgres"

	"github.com/omarss/saas/internal/dataplane/audit"
)

// applyMigrations mirrors tenancy/repo_pgx_test.go.
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
		t.Fatalf("walk: %v", err)
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

func startPostgres(t *testing.T) (*pgxpool.Pool, func()) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	c, err := tcpostgres.Run(ctx, "postgres:16",
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
	return pool, func() {
		pool.Close()
		sCtx, sc := context.WithTimeout(context.Background(), 30*time.Second)
		defer sc()
		_ = c.Terminate(sCtx)
	}
}

func setGUC(t *testing.T, pool *pgxpool.Pool, tenantID string) {
	t.Helper()
	if _, err := pool.Exec(context.Background(),
		"SELECT set_config('app.current_tenant_id', $1, false)", tenantID); err != nil {
		t.Fatalf("set GUC: %v", err)
	}
}

func TestPgxRepo_AppendThenList(t *testing.T) {
	pool, cleanup := startPostgres(t)
	defer cleanup()
	setGUC(t, pool, "tenant_pgx")

	repo := audit.NewPgxRepository(pool)
	ctx := context.Background()
	for i, action := range []string{"tenant.create", "tenant.update", "user.create"} {
		_, err := repo.Append(ctx, audit.NewEventInput{
			TenantID:      "tenant_pgx",
			ActorType:     audit.ActorUser,
			ActorID:       "user_pgx",
			Action:        action,
			ResourceType:  strings.SplitN(action, ".", 2)[0],
			ResourceID:    "tenant_pgx",
			SourceEventID: "src_pgx_" + action,
			Metadata:      map[string]any{"i": i},
		})
		if err != nil {
			t.Fatalf("Append: %v", err)
		}
	}
	rows, _, err := repo.List(ctx, audit.ListFilter{TenantID: "tenant_pgx"})
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(rows) != 3 {
		t.Fatalf("want 3 rows got %d", len(rows))
	}
}

func TestAuditEvent_DBTriggerRejectsUpdate(t *testing.T) {
	pool, cleanup := startPostgres(t)
	defer cleanup()
	setGUC(t, pool, "tenant_db_trig")

	repo := audit.NewPgxRepository(pool)
	ctx := context.Background()
	if _, err := repo.Append(ctx, audit.NewEventInput{
		TenantID:      "tenant_db_trig",
		ActorType:     audit.ActorUser,
		ActorID:       "u",
		Action:        "tenant.create",
		ResourceType:  "tenant",
		ResourceID:    "tenant_db_trig",
		SourceEventID: "src_db_trig",
	}); err != nil {
		t.Fatalf("Append: %v", err)
	}
	_, err := pool.Exec(ctx, `UPDATE audit_event SET action = 'tamper' WHERE tenant_id = 'tenant_db_trig'`)
	if err == nil {
		t.Fatal("expected trigger to reject UPDATE")
	}
	if !strings.Contains(err.Error(), "append-only") {
		t.Errorf("expected append-only error message, got %v", err)
	}
}

func TestAuditEvent_DBTriggerRejectsDelete(t *testing.T) {
	pool, cleanup := startPostgres(t)
	defer cleanup()
	setGUC(t, pool, "tenant_db_del")

	repo := audit.NewPgxRepository(pool)
	ctx := context.Background()
	if _, err := repo.Append(ctx, audit.NewEventInput{
		TenantID:      "tenant_db_del",
		ActorType:     audit.ActorUser,
		ActorID:       "u",
		Action:        "tenant.create",
		ResourceType:  "tenant",
		ResourceID:    "tenant_db_del",
		SourceEventID: "src_db_del",
	}); err != nil {
		t.Fatalf("Append: %v", err)
	}
	_, err := pool.Exec(ctx, `DELETE FROM audit_event WHERE tenant_id = 'tenant_db_del'`)
	if err == nil {
		t.Fatal("expected trigger to reject DELETE")
	}
	if !strings.Contains(err.Error(), "append-only") {
		t.Errorf("expected append-only error message, got %v", err)
	}
}

func TestPgxRepo_Idempotent_SourceEventID(t *testing.T) {
	pool, cleanup := startPostgres(t)
	defer cleanup()
	setGUC(t, pool, "tenant_idem")

	repo := audit.NewPgxRepository(pool)
	ctx := context.Background()
	in := audit.NewEventInput{
		TenantID:      "tenant_idem",
		ActorType:     audit.ActorUser,
		ActorID:       "u",
		Action:        "tenant.create",
		ResourceType:  "tenant",
		ResourceID:    "tenant_idem",
		SourceEventID: "src_idem",
	}
	first, err := repo.Append(ctx, in)
	if err != nil {
		t.Fatalf("first append: %v", err)
	}
	second, err := repo.Append(ctx, in)
	if err != nil {
		t.Fatalf("second append: %v", err)
	}
	if first.ID != second.ID {
		t.Fatalf("idempotent append should return same row id; got %q vs %q", first.ID, second.ID)
	}
}

func TestPgxRepo_VerifyChain_Integration(t *testing.T) {
	pool, cleanup := startPostgres(t)
	defer cleanup()
	setGUC(t, pool, "tenant_verify")

	repo := audit.NewPgxRepository(pool)
	ctx := context.Background()
	for _, a := range []string{"tenant.create", "tenant.update", "user.create"} {
		if _, err := repo.Append(ctx, audit.NewEventInput{
			TenantID:      "tenant_verify",
			ActorType:     audit.ActorUser,
			ActorID:       "u",
			Action:        a,
			ResourceType:  "tenant",
			ResourceID:    "tenant_verify",
			SourceEventID: "src_verify_" + a,
		}); err != nil {
			t.Fatalf("seed: %v", err)
		}
	}
	res, err := audit.VerifyChain(ctx, repo, "tenant_verify", nil)
	if err != nil {
		t.Fatalf("VerifyChain: %v", err)
	}
	if !res.Verified {
		t.Fatalf("expected verified=true got %+v", res)
	}
}
