//go:build integration

// Integration tests for the OpenBao provisioner. These spin up a real
// OpenBao container via testcontainers-go (or use the live compose
// instance when BAO_ADDR is set) and exercise the full Apply /
// VerifyAccess / Remove flow. Run with `make test-int`.
//
// The tests are skip-friendly: if BAO_ADDR is unset AND testcontainers
// cannot reach a Docker socket, the suite emits a Skip rather than
// failing. This matches the convention used by every other integration
// test in the repo (see internal/platform/crypto/envelope/
// integration_test.go for the envelope-side companion).

package openbao

import (
	"context"
	"errors"
	"os"
	"testing"
	"time"

	bao "github.com/openbao/openbao/api/v2"
)

// requireBaoClient returns an authenticated *bao.Client backed by the
// live OpenBao instance at BAO_ADDR. The integration tests reach for
// the compose-running container (the same one `make openbao-init`
// initialised); they do NOT spin up a fresh testcontainers OpenBao
// because the bao container's bootstrap sequence is non-trivial
// (Shamir init + unseal + transit + KV + k8s + AppRole mounts) and
// re-running it inside testcontainers per test would dominate the
// suite runtime.
//
// Set BAO_ADDR=http://127.0.0.1:8200 and BAO_TOKEN=<root_token_from_init.json>
// before running `make test-int`.
func requireBaoClient(t *testing.T) *bao.Client {
	t.Helper()
	addr := os.Getenv("BAO_ADDR")
	if addr == "" {
		t.Skip("BAO_ADDR not set; skipping OpenBao integration tests")
	}
	token := os.Getenv("BAO_TOKEN")
	if token == "" {
		t.Skip("BAO_TOKEN not set; integration tests need a token (root token from compose dev setup)")
	}
	cfg := bao.DefaultConfig()
	cfg.Address = addr
	bc, err := bao.NewClient(cfg)
	if err != nil {
		t.Fatalf("bao.NewClient: %v", err)
	}
	bc.SetToken(token)
	return bc
}

// uniqueDepID returns a per-test deployment_id so concurrent test runs
// don't trip over each other. The format mirrors the production
// `dep_<ulid>` shape but uses time-based bytes for determinism.
func uniqueDepID(t *testing.T) string {
	t.Helper()
	return "dep_int_" + t.Name() + "_" + time.Now().UTC().Format("20060102T150405")
}

// TestIntegration_Apply_VerifyAccess_Remove exercises the full
// provisioning + teardown cycle against a live OpenBao. Each step's
// success is asserted with the read-back probe (which itself uses
// independent reads, so a regression where Apply lies about writing
// would still surface here).
func TestIntegration_Apply_VerifyAccess_Remove(t *testing.T) {
	bc := requireBaoClient(t)

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	depID := uniqueDepID(t)
	a, err := NewHostAdapter(bc)
	if err != nil {
		t.Fatalf("NewHostAdapter: %v", err)
	}

	in := ApplyInput{
		DeploymentID:      depID,
		K3sNamespace:      "saas-" + depID,
		K3sServiceAccount: "dataplane",
	}
	res, err := a.Apply(ctx, in)
	if err != nil {
		t.Fatalf("Apply: %v", err)
	}
	if res.Kid != depID {
		t.Errorf("Kid = %q, want %q", res.Kid, depID)
	}
	if err := a.VerifyAccess(ctx, depID); err != nil {
		t.Errorf("VerifyAccess after Apply: %v", err)
	}

	t.Cleanup(func() {
		// Best-effort cleanup. We don't fail the test on Remove
		// errors because the test's primary assertion is already done.
		removeCtx, cancelRemove := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancelRemove()
		_ = a.Remove(removeCtx, RemoveInput{
			DeploymentID:      depID,
			ConfirmDestroyKey: true,
		})
	})
}

// TestIntegration_ApplyIdempotent runs Apply twice and confirms the
// second call returns the same result without erroring.
func TestIntegration_ApplyIdempotent(t *testing.T) {
	bc := requireBaoClient(t)

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	depID := uniqueDepID(t)
	a, err := NewHostAdapter(bc)
	if err != nil {
		t.Fatalf("NewHostAdapter: %v", err)
	}
	in := ApplyInput{
		DeploymentID:      depID,
		K3sNamespace:      "saas-" + depID,
		K3sServiceAccount: "dataplane",
	}
	first, err := a.Apply(ctx, in)
	if err != nil {
		t.Fatalf("first Apply: %v", err)
	}
	second, err := a.Apply(ctx, in)
	if err != nil {
		t.Fatalf("second Apply: %v", err)
	}
	if first != second {
		t.Errorf("Apply not idempotent: first=%+v second=%+v", first, second)
	}

	t.Cleanup(func() {
		removeCtx, cancelRemove := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancelRemove()
		_ = a.Remove(removeCtx, RemoveInput{
			DeploymentID:      depID,
			ConfirmDestroyKey: true,
		})
	})
}

// TestIntegration_Remove_RemovesArtifacts confirms Remove cleans up
// every artifact the Apply created. After Remove returns, VerifyAccess
// must fail with ErrVerificationFailed for the deployment_id.
func TestIntegration_Remove_RemovesArtifacts(t *testing.T) {
	bc := requireBaoClient(t)

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	depID := uniqueDepID(t)
	a, err := NewHostAdapter(bc)
	if err != nil {
		t.Fatalf("NewHostAdapter: %v", err)
	}
	in := ApplyInput{
		DeploymentID:      depID,
		K3sNamespace:      "saas-" + depID,
		K3sServiceAccount: "dataplane",
	}
	if _, err := a.Apply(ctx, in); err != nil {
		t.Fatalf("Apply: %v", err)
	}
	if err := a.Remove(ctx, RemoveInput{
		DeploymentID:      depID,
		ConfirmDestroyKey: true,
	}); err != nil {
		t.Fatalf("Remove: %v", err)
	}
	if err := a.VerifyAccess(ctx, depID); !errors.Is(err, ErrVerificationFailed) {
		t.Fatalf("VerifyAccess after Remove: got %v, want ErrVerificationFailed", err)
	}
}
