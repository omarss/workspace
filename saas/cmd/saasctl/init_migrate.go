// Phase 15 — `migrate` step for saasctl init.
//
// Runs `make migrate`, which builds the migrate binary and applies
// every up-migration on both planes. The migrate binary itself is
// idempotent: golang-migrate tracks the schema version table and is a
// no-op when already at head. The wizard exports the local-dev DB
// URLs that match compose.yaml so the operator does not have to set
// CONTROLPLANE_DATABASE_URL / DATAPLANE_DATABASE_URL by hand.

package main

import (
	"context"
	"io"
	"os"
)

// Local-dev DB URLs aligned with compose.yaml's mapped port 55432.
// The `saas` user / password / db are also defined in compose.yaml.
// #nosec G101 — local-dev compose credentials, identical to the values
// already published in compose.yaml. Real environments override via
// CONTROLPLANE_DATABASE_URL / DATAPLANE_DATABASE_URL.
const (
	localControlPlaneDB = "postgres://saas:saas@localhost:55432/saas?sslmode=disable" // #nosec G101
	localDataPlaneDB    = "postgres://saas:saas@localhost:55432/saas?sslmode=disable" // #nosec G101
)

func runMigrate(ctx context.Context, cfg *initConfig) (string, error) {
	ctx = withProjectDir(ctx, cfg.ProjectDir)
	env := []string{
		"CONTROLPLANE_DATABASE_URL=" + envOr("CONTROLPLANE_DATABASE_URL", localControlPlaneDB),
		"DATAPLANE_DATABASE_URL=" + envOr("DATAPLANE_DATABASE_URL", localDataPlaneDB),
	}
	if err := cfg.makeRunner(ctx, "migrate", env, io.Discard, os.Stderr); err != nil {
		return "", err
	}
	return "", nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
