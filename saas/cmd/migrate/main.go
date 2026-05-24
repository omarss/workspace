// Command migrate is the forward-only migration runner for both planes.
//
// Usage:
//
//	migrate -plane <controlplane|dataplane> up
//	migrate -plane <controlplane|dataplane> down [n]
//
// It reads CONTROLPLANE_DATABASE_URL or DATAPLANE_DATABASE_URL depending on
// the chosen plane, and uses a per-plane migrations table so both planes
// can live in the same database during development.
package main

import (
	"embed"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"os"

	"github.com/golang-migrate/migrate/v4"
	// Postgres driver registered via init().
	_ "github.com/golang-migrate/migrate/v4/database/postgres"
	"github.com/golang-migrate/migrate/v4/source/iofs"

	"github.com/omarss/saas/migrations"
)

func main() {
	if err := run(); err != nil {
		slog.Error("migrate failed", "err", err)
		os.Exit(1)
	}
}

func run() error {
	plane := flag.String("plane", "", "controlplane | dataplane")
	flag.Parse()

	if flag.NArg() < 1 {
		return fmt.Errorf("usage: migrate -plane <controlplane|dataplane> up|down [n]")
	}
	cmd := flag.Arg(0)

	var (
		dsn   string
		fsys  embed.FS
		root  string
		table string
	)
	switch *plane {
	case "controlplane":
		dsn = os.Getenv("CONTROLPLANE_DATABASE_URL")
		fsys = migrations.Controlplane
		root = "controlplane"
		table = "schema_migrations_controlplane"
	case "dataplane":
		dsn = os.Getenv("DATAPLANE_DATABASE_URL")
		fsys = migrations.Dataplane
		root = "dataplane"
		table = "schema_migrations_dataplane"
	default:
		return fmt.Errorf("unknown -plane=%q", *plane)
	}
	if dsn == "" {
		return fmt.Errorf("DATABASE_URL not set for plane=%s", *plane)
	}
	// Per-plane migrations table so both planes can share a database during dev.
	sep := "?"
	for _, r := range dsn {
		if r == '?' {
			sep = "&"
			break
		}
	}
	dsn = fmt.Sprintf("%s%sx-migrations-table=%s", dsn, sep, table)

	src, err := iofs.New(fsys, root)
	if err != nil {
		return fmt.Errorf("iofs: %w", err)
	}
	m, err := migrate.NewWithSourceInstance("iofs", src, dsn)
	if err != nil {
		return fmt.Errorf("migrate.New: %w", err)
	}
	defer func() { _, _ = m.Close() }()

	switch cmd {
	case "up":
		err = m.Up()
	case "down":
		steps := -1
		if flag.NArg() > 1 {
			if _, perr := fmt.Sscanf(flag.Arg(1), "%d", &steps); perr != nil {
				return fmt.Errorf("invalid steps: %w", perr)
			}
			if steps > 0 {
				steps = -steps
			}
		}
		err = m.Steps(steps)
	default:
		return fmt.Errorf("unknown cmd=%q", cmd)
	}
	if err != nil && !errors.Is(err, migrate.ErrNoChange) {
		return fmt.Errorf("migrate %s: %w", cmd, err)
	}
	slog.Info("migrate ok", "plane", *plane, "cmd", cmd)
	return nil
}
