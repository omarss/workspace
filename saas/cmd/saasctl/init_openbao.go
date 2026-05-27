// Phase 15 — `openbao-init` step for saasctl init.
//
// Delegates to `make openbao-init`, which itself is idempotent (each
// `bao secrets enable` / `bao auth enable` call is wrapped with `|| true`
// so re-runs are no-ops when the engine / auth method already exists).
// The wizard therefore does no additional pre-check beyond confirming
// the openbao service is up.

package main

import (
	"context"
	"io"
	"os"
)

func runOpenBaoInit(ctx context.Context, cfg *initConfig) (string, error) {
	ctx = withProjectDir(ctx, cfg.ProjectDir)
	if err := cfg.makeRunner(ctx, "openbao-init", nil, io.Discard, os.Stderr); err != nil {
		return "", err
	}
	return "", nil
}
