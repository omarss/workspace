//go:build integration

package identity_test

import (
	"context"
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
	"github.com/omarss/saas/internal/dataplane/identity"
	"github.com/omarss/saas/internal/platform/crypto"
	"github.com/omarss/saas/internal/platform/crypto/envelope"
)

// Phase 5 integration tests for the pgx-backed PgxRepository. These tests
// exercise:
//
//	1. Round-trip Create → Get with strict envelope encrypt + decrypt
//	2. kid-mismatch refusal BEFORE any decrypt call
//	3. RLS denies cross-tenant SELECT
//
// They mirror the Phase 2 tenancy integration tests (testcontainers-postgres).
// docker unavailability is skipped, not failed — keeps CI laptops happy.

// inMemoryEnvelope is a fake crypto.Encryptor / crypto.Decryptor for these
// integration tests. It avoids needing a real OpenBao container; the
// kid-mismatch test relies on the decrypt-side kid check happening BEFORE we
// ever hit the in-memory plaintext store, so we can prove kid binding
// without ever exercising OpenBao.
type inMemoryEnvelope struct {
	kid   string
	store map[string][]byte
}

func newInMemoryEnvelope(kid string) *inMemoryEnvelope {
	return &inMemoryEnvelope{kid: kid, store: map[string][]byte{}}
}

func (m *inMemoryEnvelope) EncryptField(_ context.Context, kid string, plaintext []byte, aad []byte) (crypto.Envelope, error) {
	// Use a deterministic key derived from len(store) so tests can assert
	// equality on the round-trip. AAD is concatenated into the lookup key.
	tag := string(aad) + ":" + string(plaintext)
	m.store[tag] = append([]byte(nil), plaintext...)
	return crypto.Envelope{
		Ciphertext: []byte(tag),
		WrappedDEK: "vault:v1:fake",
		Nonce:      make([]byte, 12),
		Algo:       "aes-256-gcm",
		KID:        kid,
		KeyVersion: 1,
	}, nil
}

func (m *inMemoryEnvelope) DecryptField(_ context.Context, env crypto.Envelope, expectedKid string, _ []byte) ([]byte, error) {
	// Mirror envelope.Client's invariant: refuse BEFORE looking anything up.
	if env.KID != expectedKid {
		return nil, envelope.ErrKidMismatch
	}
	v, ok := m.store[string(env.Ciphertext)]
	if !ok {
		return nil, errors.New("decrypt: unknown ciphertext")
	}
	return v, nil
}

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

// withTenantGUC sets app.current_tenant_id on a single connection so RLS
// honours the tenant filter. Mirrors the tenancy integration-test helper.
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

// seedTenant inserts a tenant row by hand so the platform_user FK is satisfied.
func seedTenant(t *testing.T, ctx context.Context, conn *pgx.Conn, id, slug string) {
	t.Helper()
	if _, err := conn.Exec(ctx, `INSERT INTO tenant (id, slug, name, status, metadata)
		VALUES ($1, $2, 'fixture', 'active', '{}'::jsonb)`, id, slug); err != nil {
		t.Fatalf("seed tenant: %v", err)
	}
}

const (
	intTestDeployment = "dep_integration"
	intTestTenantA    = "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	intTestTenantB    = "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"
)

func TestRepoPgx_Create_PersistsAndDecryptsRoundtrip(t *testing.T) {
	pool, cleanup := startPostgres(t)
	defer cleanup()
	ctx := context.Background()

	conn, release := withTenantGUC(t, ctx, pool, intTestTenantA)
	defer release()
	seedTenant(t, ctx, conn, intTestTenantA, "acme")

	enc := newInMemoryEnvelope(intTestDeployment)
	repo := identity.NewPgxRepository(db.New(conn), enc, enc, intTestDeployment)

	u := identity.User{
		ID:              "user_01HCCCCCCCCCCCCCCCCCCCCCCC",
		TenantID:        intTestTenantA,
		KeycloakUserID:  "kc_01HCCCCCCCCCCCCCCCCCCCCCCC",
		Email:           "alice@example.com",
		Name:            "Alice",
		Phone:           "+966500000000",
		EmailLookupHash: []byte("hash-alice"),
		Status:          identity.StatusActive,
		RowSeq:          1,
	}
	created, err := repo.Create(ctx, u)
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	// After Create, the in-memory struct's plaintext fields have been zeroed
	// by the walker (defense-in-depth). The returned struct should hydrate
	// them back from the envelope columns.
	if created.Email != "alice@example.com" {
		t.Errorf("email round-trip lost: got %q", created.Email)
	}
	if created.Name != "Alice" {
		t.Errorf("name round-trip lost: got %q", created.Name)
	}
	if created.Phone != "+966500000000" {
		t.Errorf("phone round-trip lost: got %q", created.Phone)
	}
	if created.EmailEnvelope.KID != intTestDeployment {
		t.Errorf("envelope KID not bound to deployment: %q", created.EmailEnvelope.KID)
	}

	got, err := repo.Get(ctx, intTestTenantA, created.ID)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if got.Email != "alice@example.com" {
		t.Errorf("Get email mismatch: %q", got.Email)
	}
}

func TestRepoPgx_Get_KidMismatchRefused(t *testing.T) {
	pool, cleanup := startPostgres(t)
	defer cleanup()
	ctx := context.Background()

	conn, release := withTenantGUC(t, ctx, pool, intTestTenantA)
	defer release()
	seedTenant(t, ctx, conn, intTestTenantA, "acme")

	enc := newInMemoryEnvelope(intTestDeployment)
	repo := identity.NewPgxRepository(db.New(conn), enc, enc, intTestDeployment)

	created, err := repo.Create(ctx, identity.User{
		ID:              "user_01HCCCCCCCCCCCCCCCCCCCCCCC",
		TenantID:        intTestTenantA,
		KeycloakUserID:  "kc_01HCCCCCCCCCCCCCCCCCCCCCCC",
		Email:           "bob@example.com",
		EmailLookupHash: []byte("hash-bob"),
		Status:          identity.StatusActive,
		RowSeq:          1,
	})
	if err != nil {
		t.Fatalf("Create: %v", err)
	}

	// Tamper with the row: switch email_kid to a different deployment. The
	// repo's hydrate path must refuse with ErrKidMismatch BEFORE invoking
	// the decryptor. If it failed open we would see plaintext from a
	// different deployment's transit key — a layer-5 isolation breach.
	if _, err := conn.Exec(ctx, `UPDATE platform_user SET email_kid = $1 WHERE id = $2`, "dep_other", created.ID); err != nil {
		t.Fatalf("tamper: %v", err)
	}

	if _, err := repo.Get(ctx, intTestTenantA, created.ID); !errors.Is(err, envelope.ErrKidMismatch) {
		t.Fatalf("expected ErrKidMismatch, got %v", err)
	}
}

func TestRepoPgx_RLS_DenysCrossTenantSelect(t *testing.T) {
	pool, cleanup := startPostgres(t)
	defer cleanup()
	ctx := context.Background()

	// Connection A: bound to tenant A; create alice.
	connA, releaseA := withTenantGUC(t, ctx, pool, intTestTenantA)
	defer releaseA()
	seedTenant(t, ctx, connA, intTestTenantA, "acme")

	enc := newInMemoryEnvelope(intTestDeployment)
	repoA := identity.NewPgxRepository(db.New(connA), enc, enc, intTestDeployment)
	if _, err := repoA.Create(ctx, identity.User{
		ID:              "user_01HDDDDDDDDDDDDDDDDDDDDDDD",
		TenantID:        intTestTenantA,
		KeycloakUserID:  "kc_01HDDDDDDDDDDDDDDDDDDDDDDD",
		Email:           "alice@example.com",
		EmailLookupHash: []byte("hash-cross-1"),
		Status:          identity.StatusActive,
		RowSeq:          1,
	}); err != nil {
		t.Fatalf("Create tenantA user: %v", err)
	}

	// Connection B: bound to tenant B. SELECT must return zero rows.
	connB, releaseB := withTenantGUC(t, ctx, pool, intTestTenantB)
	defer releaseB()
	seedTenant(t, ctx, connB, intTestTenantB, "globex")

	var count int
	if err := connB.QueryRow(ctx, "SELECT count(*) FROM platform_user").Scan(&count); err != nil {
		t.Fatalf("count: %v", err)
	}
	if count != 0 {
		t.Fatalf("RLS leak: tenant B saw %d platform_user rows from tenant A", count)
	}
}
