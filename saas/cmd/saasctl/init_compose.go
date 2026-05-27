// Phase 15 — `compose-up` and `wait-healthy` steps for saasctl init.
//
// compose-up shells out to `make compose-up` (which itself runs
// `docker compose ... up -d --wait` — the --wait flag blocks until all
// healthchecks pass). The wait-healthy step is therefore mostly a
// belt-and-braces re-check: it queries `docker compose ps --format json`
// and reports any service that isn't in the "running (healthy)" state.

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"
)

// runComposeUp brings up the local stack via `make compose-up`. The
// underlying compose invocation uses --wait, so first-run blocks until
// every service reports healthy; subsequent runs are idempotent (no-op
// for services already running).
func runComposeUp(ctx context.Context, cfg *initConfig) (string, error) {
	if alreadyHealthy(ctx, cfg) {
		return "already done", nil
	}
	ctx = withProjectDir(ctx, cfg.ProjectDir)
	if err := cfg.makeRunner(ctx, "compose-up", nil, io.Discard, os.Stderr); err != nil {
		return "", err
	}
	return "", nil
}

// waitHealthy polls docker compose for up to 90s. compose-up already
// uses --wait, but we re-check so flaky environments (slow disk / cold
// images) get a clear error before we hand off to the next step.
func waitHealthy(ctx context.Context, cfg *initConfig) (string, error) {
	deadline := nowUTC().Add(90 * time.Second)
	for {
		unhealthy, err := listUnhealthyServices(ctx, cfg)
		if err == nil && len(unhealthy) == 0 {
			return "", nil
		}
		if nowUTC().After(deadline) {
			if err != nil {
				return "", fmt.Errorf("docker compose ps: %w", err)
			}
			return "", fmt.Errorf("services still unhealthy after 90s: %s", strings.Join(unhealthy, ", "))
		}
		select {
		case <-ctx.Done():
			return "", ctx.Err()
		case <-time.After(3 * time.Second):
		}
	}
}

// alreadyHealthy is a cheap pre-flight: if every compose service is
// already running healthy, we skip the make call entirely (idempotent
// re-run optimization).
func alreadyHealthy(ctx context.Context, cfg *initConfig) bool {
	unhealthy, err := listUnhealthyServices(ctx, cfg)
	if err != nil {
		return false
	}
	return len(unhealthy) == 0
}

// listUnhealthyServices returns the names of compose services that are
// not in a healthy state. An empty slice means everything is fine.
// Falls back to podman compose when docker is missing. The compose
// probe is injectable for tests via cfg.composeChecker.
func listUnhealthyServices(ctx context.Context, cfg *initConfig) ([]string, error) {
	checker := cfg.composeChecker
	if checker == nil {
		checker = composePSJSON
	}
	dir := cfg.ProjectDir
	if dir == "" {
		dir = projectDirFromCtx(ctx)
	}
	out, err := checker(ctx, dir)
	if err != nil {
		return nil, err
	}
	if len(out) == 0 {
		// `compose ps` returned no rows — stack is down.
		return []string{"(stack not started)"}, nil
	}
	var bad []string
	for _, svc := range out {
		if !isHealthy(svc) {
			bad = append(bad, svc.Name)
		}
	}
	return bad, nil
}

// composeService is the relevant subset of `docker compose ps --format json`.
// Field names match docker/compose v2's output; podman emits the same
// schema because of the compose-spec project.
type composeService struct {
	Name    string `json:"Name"`
	Service string `json:"Service"`
	State   string `json:"State"`
	Health  string `json:"Health"`
	Status  string `json:"Status"`
}

func isHealthy(s composeService) bool {
	// A service with no healthcheck shows Health="" — treat State=="running"
	// as sufficient in that case; this matches `--wait` semantics.
	if strings.EqualFold(s.State, "running") {
		if s.Health == "" || strings.EqualFold(s.Health, "healthy") {
			return true
		}
	}
	return false
}

// composePSJSON shells out to docker compose first, podman compose
// second. Returns (services, nil) on success. Returns (nil, err) only
// when both runtimes failed.
func composePSJSON(ctx context.Context, dir string) ([]composeService, error) {
	for _, runtime := range [][]string{
		{"docker", "compose", "ps", "--format", "json", "--all"},
		{"podman", "compose", "ps", "--format", "json"},
	} {
		cmd := exec.CommandContext(ctx, runtime[0], runtime[1:]...) // #nosec G204 — runtime list is a fixed allowlist of compose CLIs
		cmd.Dir = dir
		var stdout, stderr bytes.Buffer
		cmd.Stdout = &stdout
		cmd.Stderr = &stderr
		if err := cmd.Run(); err != nil {
			continue
		}
		svcs, err := parseComposeJSON(stdout.Bytes())
		if err != nil {
			continue
		}
		return svcs, nil
	}
	return nil, fmt.Errorf("no working compose runtime found (tried docker, podman)")
}

// parseComposeJSON tolerates both newline-delimited JSON (docker
// compose v2's default) and a single JSON array (older variants).
func parseComposeJSON(raw []byte) ([]composeService, error) {
	trimmed := bytes.TrimSpace(raw)
	if len(trimmed) == 0 {
		return nil, nil
	}
	// JSON array form.
	if trimmed[0] == '[' {
		var arr []composeService
		if err := json.Unmarshal(trimmed, &arr); err != nil {
			return nil, err
		}
		return arr, nil
	}
	// NDJSON form.
	var out []composeService
	for _, line := range bytes.Split(trimmed, []byte("\n")) {
		line = bytes.TrimSpace(line)
		if len(line) == 0 {
			continue
		}
		var svc composeService
		if err := json.Unmarshal(line, &svc); err != nil {
			return nil, err
		}
		out = append(out, svc)
	}
	return out, nil
}
