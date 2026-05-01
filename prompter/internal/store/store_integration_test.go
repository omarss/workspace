//go:build integration

// Integration tests for the sqlc-generated store. They validate that
// generated types and SQL constraints behave as expected against a real
// Postgres 18 instance.
//
// Run with `make test-int`. The Makefile target wires up the dev DB DSN
// and uses --network=host so the builder container can reach 127.0.0.1.
package store_test

import (
	"context"
	"fmt"
	"os"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/omarss/prompter/internal/store"
)

func newTestPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("PROMPTER_TEST_DB_DSN")
	if dsn == "" {
		t.Skip("PROMPTER_TEST_DB_DSN not set; skipping integration test")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatalf("pgxpool.New: %v", err)
	}
	t.Cleanup(pool.Close)
	if err := pool.Ping(ctx); err != nil {
		t.Fatalf("ping: %v", err)
	}
	return pool
}

func strPtr(v string) *string { return &v }

func TestCreateUser_RoundTrip(t *testing.T) {
	ctx := context.Background()
	q := store.New(newTestPool(t))

	email := fmt.Sprintf("rt+%s@example.com", uuid.NewString())
	created, err := q.CreateUser(ctx, store.CreateUserParams{
		Email:       strPtr(email),
		DisplayName: "round-trip",
	})
	if err != nil {
		t.Fatalf("CreateUser: %v", err)
	}

	fetched, err := q.GetUserByEmail(ctx, strPtr(email))
	if err != nil {
		t.Fatalf("GetUserByEmail: %v", err)
	}
	if fetched.ID != created.ID {
		t.Fatalf("id mismatch: got %s, want %s", fetched.ID, created.ID)
	}
	if fetched.DisplayName != "round-trip" {
		t.Fatalf("display_name: got %q, want %q", fetched.DisplayName, "round-trip")
	}
}

// CHECK constraint users_identifier_present must reject rows missing both
// email and phone — auth flows depend on that invariant.
func TestCreateUser_RequiresEmailOrPhone(t *testing.T) {
	ctx := context.Background()
	q := store.New(newTestPool(t))

	_, err := q.CreateUser(ctx, store.CreateUserParams{
		DisplayName: "no-id",
	})
	if err == nil {
		t.Fatalf("expected CHECK violation, got nil")
	}
}

// UNIQUE on email must hold — re-registering the same address can't shadow
// the first row.
func TestCreateUser_EmailUnique(t *testing.T) {
	ctx := context.Background()
	q := store.New(newTestPool(t))

	email := fmt.Sprintf("uniq+%s@example.com", uuid.NewString())
	if _, err := q.CreateUser(ctx, store.CreateUserParams{
		Email:       strPtr(email),
		DisplayName: "first",
	}); err != nil {
		t.Fatalf("first insert: %v", err)
	}
	if _, err := q.CreateUser(ctx, store.CreateUserParams{
		Email:       strPtr(email),
		DisplayName: "dup",
	}); err == nil {
		t.Fatalf("expected unique violation, got nil")
	}
}
