// Phase 15 — Make orchestration helpers for `saasctl init`.
//
// Each init step that wraps an existing Makefile target funnels through
// realMakeRunner. We capture stdout/stderr so the wizard can show a
// concise "OK" line and only spill the make output on failure.

package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
)

// realMakeRunner executes `make -C <dir> <target>` with the given extra
// env vars. The combined stdout+stderr stream is mirrored to the passed
// writer on failure so the operator sees what went wrong without the
// happy-path output drowning the wizard.
func realMakeRunner(ctx context.Context, target string, extraEnv []string, stdout, stderr io.Writer) error {
	dir := projectDirFromCtx(ctx)
	args := []string{"-C", dir, target}
	cmd := exec.CommandContext(ctx, "make", args...) // #nosec G204 — target is a fixed string constant in init_*.go
	cmd.Env = append(os.Environ(), extraEnv...)
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	if err := cmd.Run(); err != nil {
		_, _ = io.Copy(stderr, &out)
		return fmt.Errorf("make %s: %w", target, err)
	}
	_, _ = io.Copy(stdout, &out)
	return nil
}

// projectDirFromCtx threads the resolved project directory through
// context.Context. Using a context key (rather than a global) keeps the
// runner pure for tests.
type projectDirKey struct{}

func projectDirFromCtx(ctx context.Context) string {
	if v, ok := ctx.Value(projectDirKey{}).(string); ok && v != "" {
		return v
	}
	cwd, _ := os.Getwd()
	return cwd
}

func withProjectDir(ctx context.Context, dir string) context.Context {
	return context.WithValue(ctx, projectDirKey{}, dir)
}
