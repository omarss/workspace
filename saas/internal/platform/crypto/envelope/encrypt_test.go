package envelope_test

import (
	"context"
	"errors"
	"testing"

	"github.com/omarss/saas/internal/platform/crypto/envelope"
)

// TestDecrypt_RefusesEmptyExpectedKid pins the layer-5 contract: callers
// MUST supply the expected kid (typically from the request context's
// deployment_id). An empty expected kid would degrade Decrypt into "trust
// the row's kid", which is exactly the foot-gun we're guarding against.
func TestDecrypt_RefusesEmptyExpectedKid(t *testing.T) {
	c := &envelope.Client{}
	env := envelope.Envelope{KID: "dep_A", WrappedDEK: "vault:v1:abc", Nonce: make([]byte, 12)}
	_, err := c.Decrypt(context.Background(), env, "", []byte("aad"))
	if !errors.Is(err, envelope.ErrMissingExpectedKID) {
		t.Fatalf("expected ErrMissingExpectedKID, got %v", err)
	}
}

// TestDecrypt_RefusesEmptyRowKID is the symmetric guard. If a row was
// persisted without a kid, refuse rather than fall back to the expected
// kid (which would let an attacker forge "decryptable" rows).
func TestDecrypt_RefusesEmptyRowKID(t *testing.T) {
	c := &envelope.Client{}
	env := envelope.Envelope{KID: "", WrappedDEK: "vault:v1:abc", Nonce: make([]byte, 12)}
	_, err := c.Decrypt(context.Background(), env, "dep_A", []byte("aad"))
	if !errors.Is(err, envelope.ErrEmptyKID) {
		t.Fatalf("expected ErrEmptyKID, got %v", err)
	}
}

// TestDecrypt_KidMismatchRefusedBeforeAPICall is the linchpin of layer 5.
// It exercises the path with a row kid that disagrees with the caller's
// expected kid. The Client has no auth token wired (Client{} zero value),
// so any OpenBao API call would surface a transport error. The test
// requires ErrKidMismatch — meaning the refusal happens BEFORE any
// network attempt.
func TestDecrypt_KidMismatchRefusedBeforeAPICall(t *testing.T) {
	c := &envelope.Client{}
	env := envelope.Envelope{KID: "dep_OTHER", WrappedDEK: "vault:v1:abc", Nonce: make([]byte, 12)}
	_, err := c.Decrypt(context.Background(), env, "dep_SELF", []byte("aad"))
	if !errors.Is(err, envelope.ErrKidMismatch) {
		t.Fatalf("expected ErrKidMismatch, got %v", err)
	}
}

// TestEncrypt_RejectsInvalidKid guards against path-traversal at the kid
// argument. A kid containing "/" or "../" would let the call escape into
// another transit key namespace.
func TestEncrypt_RejectsInvalidKid(t *testing.T) {
	c := &envelope.Client{}
	for _, kid := range []string{"", "dep/A", "dep A", "../etc/passwd"} {
		_, err := c.Encrypt(context.Background(), kid, []byte("data"), []byte("aad"))
		if err == nil {
			t.Errorf("expected error for kid %q, got nil", kid)
		}
	}
}

// TestEncrypt_EmptyPlaintextIsNoOp confirms the documented fast-path:
// empty plaintext skips the OpenBao call and returns a zero Envelope.
// Repository code relies on this when persisting a Null field.
func TestEncrypt_EmptyPlaintextIsNoOp(t *testing.T) {
	c := &envelope.Client{}
	env, err := c.Encrypt(context.Background(), "dep_A", nil, []byte("aad"))
	if err != nil {
		t.Fatalf("Encrypt(nil): %v", err)
	}
	if env.KID != "" || len(env.Ciphertext) != 0 || env.WrappedDEK != "" {
		t.Fatalf("expected zero envelope, got %+v", env)
	}
}

// TestRotateRewrap_ValidateKid exercises the same kid-validation path on
// the maintenance helpers; if they accepted "../" we'd let an operator
// rotate the wrong key by accident.
func TestRotateRewrap_ValidateKid(t *testing.T) {
	c := &envelope.Client{}
	if err := c.RotateKey(context.Background(), ""); err == nil {
		t.Errorf("RotateKey(empty) should error")
	}
	if _, _, err := c.Rewrap(context.Background(), "dep/A", "vault:v1:abc"); err == nil {
		t.Errorf("Rewrap with bad kid should error")
	}
}
