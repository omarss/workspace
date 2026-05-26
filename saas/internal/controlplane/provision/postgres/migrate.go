package postgres

import (
	"context"
	"errors"
	"fmt"

	"github.com/golang-migrate/migrate/v4"
	// Postgres driver registered via init().
	_ "github.com/golang-migrate/migrate/v4/database/postgres"
	"github.com/golang-migrate/migrate/v4/source/iofs"

	"github.com/omarss/saas/migrations"
)

// migrationsApplier abstracts the data-plane migration runner so tests
// can inject a stub. The production implementation in defaultMigrations
// uses the embedded migrations + golang-migrate.
type migrationsApplier interface {
	// Up applies every pending migration. Idempotent: returns nil when
	// the schema is already at the latest version (golang-migrate's
	// ErrNoChange is squashed here so the orchestration step is plain).
	Up(ctx context.Context, dsn string) error
}

// defaultMigrations runs the embedded data-plane migrations via
// golang-migrate's iofs source + postgres driver. The same pattern
// powers cmd/migrate; this adapter uses the same migrations.Dataplane
// embed.FS so the schema applied per-Deployment is byte-identical to
// the schema applied by the dev-host migrate runner.
type defaultMigrations struct{}

// Up implements migrationsApplier.Up. The per-deployment migrations
// table is `schema_migrations_dataplane` (same name as cmd/migrate
// uses) so a future merge of multiple deployments' schemas onto one
// DB would not collide — the table name is plane-scoped, not
// deployment-scoped.
//
// We append the migrations table name to the DSN here rather than via
// migrate.WithCustomMigrationsTable because the Postgres driver reads
// the `x-migrations-table` query parameter at connect time; adding it
// post-construction is a no-op.
func (defaultMigrations) Up(ctx context.Context, dsn string) error {
	src, err := iofs.New(migrations.Dataplane, "dataplane")
	if err != nil {
		return fmt.Errorf("iofs source: %w", err)
	}
	dsnWithTable := appendQueryParam(dsn, "x-migrations-table", "schema_migrations_dataplane")
	m, err := migrate.NewWithSourceInstance("iofs", src, dsnWithTable)
	if err != nil {
		return fmt.Errorf("migrate new: %w", err)
	}
	defer func() {
		// migrate.Close returns two errors (source + database); we
		// discard both because the migration result is what matters.
		_, _ = m.Close()
	}()

	// golang-migrate exposes no context-aware Up; we let the caller's
	// ctx govern only the connection lifecycle. The migration set is
	// small enough (~8 files) that a context cancel mid-Up is the
	// operator's responsibility to recover from.
	_ = ctx

	if err := m.Up(); err != nil && !errors.Is(err, migrate.ErrNoChange) {
		return err
	}
	return nil
}

// appendQueryParam appends `key=value` to a DSN's query string,
// preserving any existing query parameters. Handles both `?` and `&`
// separators.
func appendQueryParam(dsn, key, value string) string {
	sep := "?"
	for _, r := range dsn {
		if r == '?' {
			sep = "&"
			break
		}
	}
	return dsn + sep + key + "=" + value
}
