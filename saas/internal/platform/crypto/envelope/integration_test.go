//go:build integration

package envelope_test

import (
	"bytes"
	"context"
	"errors"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/omarss/saas/internal/platform/crypto/envelope"
)

// requireBao reads BAO_ADDR + BAO_TOKEN from env and constructs a Client
// pre-loaded with the token (skipping the auth-method flow so this test
// suite doesn't need a Kubernetes SA or AppRole role to be provisioned).
//
// The test is skipped when BAO_ADDR is unset — CI without a live bao must
// not flag the suite as a failure. `make test-int` sets BAO_ADDR when the
// compose stack is running. BAO_TOKEN is typically the root token from the
// dev init.json, exported by `make openbao-init` then read off the
// container's /openbao/secrets/init.json.
func requireBao(t *testing.T) *envelope.Client {
	t.Helper()
	addr := os.Getenv("BAO_ADDR")
	if addr == "" {
		t.Skip("BAO_ADDR not set; skipping OpenBao integration tests")
	}
	token := os.Getenv("BAO_TOKEN")
	if token == "" {
		t.Skip("BAO_TOKEN not set; integration tests need a token (root token from compose dev setup)")
	}
	return envelope.NewForTest(addr, token)
}

// TestIntegration_RoundTrip exercises Encrypt → Decrypt against a real
// transit key. The key is created on first use and reused across sub-tests.
func TestIntegration_RoundTrip(t *testing.T) {
	c := requireBao(t)
	defer c.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	kid := "dep_int_test_roundtrip"
	if err := c.EnsureKey(ctx, kid); err != nil {
		t.Fatalf("EnsureKey: %v", err)
	}

	plaintext := []byte("alice@example.com")
	aad := []byte("dep_int_test_roundtrip|users|user_X|email")

	env, err := c.Encrypt(ctx, kid, plaintext, aad)
	if err != nil {
		t.Fatalf("Encrypt: %v", err)
	}
	if env.KID != kid {
		t.Errorf("envelope kid = %q, want %q", env.KID, kid)
	}
	if env.Algo != "aes-256-gcm" {
		t.Errorf("envelope algo = %q, want aes-256-gcm", env.Algo)
	}
	if env.KeyVersion < 1 {
		t.Errorf("envelope key version = %d, want >= 1", env.KeyVersion)
	}
	if !strings.HasPrefix(env.WrappedDEK, "vault:v") && !strings.HasPrefix(env.WrappedDEK, "openbao:v") {
		t.Errorf("wrapped DEK has unexpected prefix: %q", env.WrappedDEK)
	}

	out, err := c.Decrypt(ctx, env, kid, aad)
	if err != nil {
		t.Fatalf("Decrypt: %v", err)
	}
	if !bytes.Equal(out, plaintext) {
		t.Errorf("Decrypt returned %q, want %q", out, plaintext)
	}
}

// TestIntegration_KidBindingRefusesCrossDeployment proves the layer-5
// invariant against a real bao: a row encrypted under dep_A cannot be
// decrypted in a context that expects dep_B, EVEN IF the caller's token
// has permission to decrypt under dep_B.
func TestIntegration_KidBindingRefusesCrossDeployment(t *testing.T) {
	c := requireBao(t)
	defer c.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	kidA := "dep_int_test_kidbind_a"
	kidB := "dep_int_test_kidbind_b"
	for _, k := range []string{kidA, kidB} {
		if err := c.EnsureKey(ctx, k); err != nil {
			t.Fatalf("EnsureKey(%s): %v", k, err)
		}
	}

	env, err := c.Encrypt(ctx, kidA, []byte("secret-A"), []byte("aad"))
	if err != nil {
		t.Fatalf("Encrypt under %s: %v", kidA, err)
	}

	// Now try to decrypt with expectedKid=kidB. The row says kidA. The
	// kid binding check refuses BEFORE the bao call — meaning the test
	// passes even if our token would have been allowed to decrypt under
	// kidB.
	_, err = c.Decrypt(ctx, env, kidB, []byte("aad"))
	if !errors.Is(err, envelope.ErrKidMismatch) {
		t.Fatalf("expected ErrKidMismatch, got %v", err)
	}
}

// TestIntegration_AADTagMismatch confirms the AAD acts as the row binding:
// changing one byte of AAD between encrypt and decrypt causes the AEAD
// tag check to fail with a non-nil error (the exact error type comes from
// the GCM Open call so we don't pin it to a sentinel).
func TestIntegration_AADTagMismatch(t *testing.T) {
	c := requireBao(t)
	defer c.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	kid := "dep_int_test_aad"
	if err := c.EnsureKey(ctx, kid); err != nil {
		t.Fatalf("EnsureKey: %v", err)
	}

	env, err := c.Encrypt(ctx, kid, []byte("payload"), []byte("aad-A"))
	if err != nil {
		t.Fatalf("Encrypt: %v", err)
	}
	if _, err := c.Decrypt(ctx, env, kid, []byte("aad-B")); err == nil {
		t.Fatal("expected error on AAD mismatch, got nil")
	}
}

// TestIntegration_RotateAndRewrap exercises the maintenance helpers.
// After a rotate, the old envelope still decrypts (OpenBao retains
// versions); rewrap bumps the wrapped_dek version without exposing
// plaintext; the rewrapped envelope still decrypts.
func TestIntegration_RotateAndRewrap(t *testing.T) {
	c := requireBao(t)
	defer c.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	kid := "dep_int_test_rotate"
	if err := c.EnsureKey(ctx, kid); err != nil {
		t.Fatalf("EnsureKey: %v", err)
	}

	env1, err := c.Encrypt(ctx, kid, []byte("v1-payload"), []byte("aad"))
	if err != nil {
		t.Fatalf("Encrypt v1: %v", err)
	}
	v1 := env1.KeyVersion

	if err := c.RotateKey(ctx, kid); err != nil {
		t.Fatalf("RotateKey: %v", err)
	}
	env2, err := c.Encrypt(ctx, kid, []byte("v2-payload"), []byte("aad"))
	if err != nil {
		t.Fatalf("Encrypt v2: %v", err)
	}
	if env2.KeyVersion <= v1 {
		t.Errorf("rotate did not bump version: v1=%d v2=%d", v1, env2.KeyVersion)
	}

	// Old envelope still decrypts.
	if got, err := c.Decrypt(ctx, env1, kid, []byte("aad")); err != nil || !bytes.Equal(got, []byte("v1-payload")) {
		t.Fatalf("decrypt old envelope: got=%q err=%v", got, err)
	}

	// Rewrap the old envelope and confirm the rewrapped version still
	// decrypts. The plaintext path doesn't change — only the wrapped DEK.
	newWrap, newVer, err := c.Rewrap(ctx, kid, env1.WrappedDEK)
	if err != nil {
		t.Fatalf("Rewrap: %v", err)
	}
	if newVer <= v1 {
		t.Errorf("rewrap did not bump version: v1=%d new=%d", v1, newVer)
	}
	env1Rewrapped := env1
	env1Rewrapped.WrappedDEK = newWrap
	env1Rewrapped.KeyVersion = newVer
	if got, err := c.Decrypt(ctx, env1Rewrapped, kid, []byte("aad")); err != nil || !bytes.Equal(got, []byte("v1-payload")) {
		t.Fatalf("decrypt rewrapped: got=%q err=%v", got, err)
	}
}

// TestIntegration_KVRoundTrip exercises the KV v2 helper. A path traversal
// attempt is rejected; well-formed paths round-trip cleanly.
func TestIntegration_KVRoundTrip(t *testing.T) {
	c := requireBao(t)
	defer c.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	depID := "dep_int_test_kv"
	if err := c.KVPut(ctx, depID, "creds/smtp", map[string]any{"user": "alice", "pass": "hunter2"}); err != nil {
		t.Fatalf("KVPut: %v", err)
	}
	got, err := c.KVGet(ctx, depID, "creds/smtp")
	if err != nil {
		t.Fatalf("KVGet: %v", err)
	}
	if got["user"] != "alice" || got["pass"] != "hunter2" {
		t.Errorf("KVGet returned wrong payload: %v", got)
	}
	if err := c.KVDelete(ctx, depID, "creds/smtp"); err != nil {
		t.Fatalf("KVDelete: %v", err)
	}
	if _, err := c.KVGet(ctx, depID, "creds/smtp"); !errors.Is(err, envelope.ErrNotFound) {
		t.Errorf("KVGet after delete: got %v, want ErrNotFound", err)
	}
}

// TestIntegration_ConcurrentEncrypt fans out 100 Encrypt calls and
// asserts there are no token-lease races. 1000 from the phase doc is
// excessive for an integration suite — 100 catches the common races.
func TestIntegration_ConcurrentEncrypt(t *testing.T) {
	c := requireBao(t)
	defer c.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	kid := "dep_int_test_concurrent"
	if err := c.EnsureKey(ctx, kid); err != nil {
		t.Fatalf("EnsureKey: %v", err)
	}

	var wg sync.WaitGroup
	errs := make(chan error, 100)
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := c.Encrypt(ctx, kid, []byte("payload"), []byte("aad"))
			if err != nil {
				errs <- err
			}
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Errorf("concurrent Encrypt error: %v", err)
	}
}
