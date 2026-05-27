// Phase 15 — `realm-import` step for saasctl init.
//
// `make operators-realm-import` boots a one-shot Keycloak container with
// the operators-realm.json mounted at /opt/keycloak/data/import and
// then exits. The compose Keycloak service imports the saas-data-local
// realm at startup via its own --import-realm flag, so this step only
// needs to handle the operators realm.
//
// Idempotency: the one-shot container exits cleanly when the realm
// already exists; re-running is a no-op.

package main

import (
	"context"
	"io"
	"os"
)

func runRealmImport(ctx context.Context, cfg *initConfig) (string, error) {
	ctx = withProjectDir(ctx, cfg.ProjectDir)
	if err := cfg.makeRunner(ctx, "operators-realm-import", nil, io.Discard, os.Stderr); err != nil {
		return "", err
	}
	return "", nil
}
