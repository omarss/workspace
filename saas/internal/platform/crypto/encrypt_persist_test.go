package crypto_test

import (
	"context"
	"errors"
	"testing"

	"github.com/omarss/saas/internal/platform/crypto"
)

type stubEncryptor struct {
	called  []string
	lastKID string
	// lastPT is the last plaintext seen; tests use it to assert the AAD-
	// derived ciphertext store key when needed.
	lastPT []byte
}

func (s *stubEncryptor) EncryptField(_ context.Context, kid string, plaintext []byte, aad []byte) (crypto.Envelope, error) {
	s.called = append(s.called, string(aad))
	s.lastKID = kid
	s.lastPT = append(s.lastPT[:0], plaintext...)
	// Bind the ciphertext to the AAD so the stub Decryptor can verify the
	// round-trip — mirrors the production AEAD authentication tag.
	return crypto.Envelope{Ciphertext: append([]byte(nil), aad...), KID: kid}, nil
}

// stubDecryptor pairs with stubEncryptor: it returns the plaintext stored
// under the AAD-derived ciphertext key when (kid, aad) round-trip cleanly,
// and refuses with errAEAD when the AAD does not match what was sealed.
type stubDecryptor struct {
	store map[string][]byte // aad -> plaintext
}

func newStubDecryptor() *stubDecryptor {
	return &stubDecryptor{store: map[string][]byte{}}
}

var errAEAD = errors.New("crypto: AEAD verify failed")

func (s *stubDecryptor) DecryptField(_ context.Context, env crypto.Envelope, expectedKid string, aad []byte) ([]byte, error) {
	if env.KID != expectedKid {
		return nil, errAEAD
	}
	// AEAD authenticity: the encryptor sealed under AAD = env.Ciphertext (in
	// this stub). Mismatched AAD means cross-resource swap → fail.
	if string(aad) != string(env.Ciphertext) {
		return nil, errAEAD
	}
	pt, ok := s.store[string(aad)]
	if !ok {
		return nil, errAEAD
	}
	return pt, nil
}

type sample struct {
	UserID string `json:"user_id"`
	Email  string `json:"email" pii:"true"`
	Phone  string `json:"phone" sensitive:"true"`
	Note   string `json:"note"`
}

func TestEncryptPIIFields_WalksTaggedFields(t *testing.T) {
	enc := &stubEncryptor{}
	v := &sample{UserID: "u_X", Email: "alice@example.com", Phone: "+966500000000", Note: "ok"}
	if err := crypto.EncryptPIIFields(context.Background(), enc, "dep_X", "user", "u_X", v); err != nil {
		t.Fatalf("EncryptPIIFields: %v", err)
	}
	if v.Email != "" || v.Phone != "" {
		t.Errorf("plaintext not cleared: %+v", v)
	}
	if v.UserID != "u_X" || v.Note != "ok" {
		t.Errorf("non-PII fields modified: %+v", v)
	}
	if len(enc.called) != 2 {
		t.Errorf("expected 2 EncryptField calls, got %d (%v)", len(enc.called), enc.called)
	}
	// AAD must bind deployment_id + resource_type + resource_id + field_name.
	wantEmail := "dep_X|user|u_X|Email"
	wantPhone := "dep_X|user|u_X|Phone"
	got := map[string]bool{}
	for _, aad := range enc.called {
		got[aad] = true
	}
	if !got[wantEmail] || !got[wantPhone] {
		t.Errorf("AAD did not bind the (deployment, resource, field) quad: got %v", enc.called)
	}
}

func TestEncryptPIIFields_NotPointer(t *testing.T) {
	enc := &stubEncryptor{}
	err := crypto.EncryptPIIFields(context.Background(), enc, "dep_X", "user", "u_X", sample{Email: "x@y"})
	if !errors.Is(err, crypto.ErrNotPointer) {
		t.Fatalf("expected ErrNotPointer, got %v", err)
	}
}

func TestEncryptPIIFields_NoEncryptor(t *testing.T) {
	err := crypto.EncryptPIIFields(context.Background(), nil, "dep_X", "user", "u_X", &sample{})
	if !errors.Is(err, crypto.ErrNoEncryptor) {
		t.Fatalf("expected ErrNoEncryptor, got %v", err)
	}
}

// sampleWithSibling exercises the Phase 4 sibling-envelope convention. The
// walker should populate EmailEnvelope when it encrypts Email and leave the
// plaintext column empty so the row never carries the unencrypted value
// past the persistence boundary.
type sampleWithSibling struct {
	UserID        string          `json:"user_id"`
	Email         string          `json:"email" pii:"true"`
	EmailEnvelope crypto.Envelope // populated by the walker
	Note          string          `json:"note"`
}

func TestEncryptPIIFields_PopulatesSiblingEnvelope(t *testing.T) {
	enc := &stubEncryptor{}
	v := &sampleWithSibling{UserID: "u_X", Email: "alice@example.com", Note: "ok"}
	if err := crypto.EncryptPIIFields(context.Background(), enc, "dep_X", "user", "u_X", v); err != nil {
		t.Fatalf("EncryptPIIFields: %v", err)
	}
	if v.Email != "" {
		t.Errorf("plaintext Email not cleared: %q", v.Email)
	}
	if v.EmailEnvelope.KID != "dep_X" {
		t.Errorf("sibling envelope kid not bound to deployment id: %+v", v.EmailEnvelope)
	}
	if string(v.EmailEnvelope.Ciphertext) != "dep_X|user|u_X|Email" {
		t.Errorf("sibling envelope ciphertext (stub-encodes AAD) wrong: %s", string(v.EmailEnvelope.Ciphertext))
	}
}

// sampleStrictMissingSibling intentionally tags Email PII without declaring
// the EmailEnvelope sibling so the strict walker raises ErrEnvelopeFieldMissing.
// This is the regression that Phase 5 introduces: silent envelope drop on a
// PII column is a data-loss / leak hazard; strict mode fails the walker loudly.
type sampleStrictMissingSibling struct {
	UserID string `json:"user_id"`
	Email  string `json:"email" pii:"true"`
	Note   string `json:"note"`
}

func TestEncryptPIIFieldsStrict_MissingSiblingFailsLoudly(t *testing.T) {
	enc := &stubEncryptor{}
	v := &sampleStrictMissingSibling{UserID: "u_X", Email: "alice@example.com", Note: "ok"}
	err := crypto.EncryptPIIFieldsStrict(context.Background(), enc, "dep_X", "user", "u_X", v)
	if !errors.Is(err, crypto.ErrEnvelopeFieldMissing) {
		t.Fatalf("expected ErrEnvelopeFieldMissing, got %v", err)
	}
	// Plaintext must remain intact when the walker refuses — the caller has
	// not committed the row yet, so reverting cleanly matters.
	if v.Email != "alice@example.com" {
		t.Errorf("plaintext mutated despite strict-mode failure: %q", v.Email)
	}
}

func TestEncryptPIIFieldsStrict_HappyPath(t *testing.T) {
	enc := &stubEncryptor{}
	v := &sampleWithSibling{UserID: "u_X", Email: "alice@example.com", Note: "ok"}
	if err := crypto.EncryptPIIFieldsStrict(context.Background(), enc, "dep_X", "user", "u_X", v); err != nil {
		t.Fatalf("EncryptPIIFieldsStrict: %v", err)
	}
	if v.Email != "" {
		t.Errorf("plaintext Email not cleared: %q", v.Email)
	}
	if v.EmailEnvelope.KID != "dep_X" {
		t.Errorf("sibling envelope kid not bound to deployment id: %+v", v.EmailEnvelope)
	}
}

// TestEncryptPIIFieldsStrict_AADRejectsCrossResourceSwap is the regression
// for the Phase 6 audit finding: before the AAD format was extended, a
// ciphertext stolen from channel_A could be pasted into channel_B and the
// AEAD verify would succeed (same kid + same field name). With the full
// (deployment, resource_type, resource_id, field) AAD, a swap fails.
func TestEncryptPIIFieldsStrict_AADRejectsCrossResourceSwap(t *testing.T) {
	enc := &stubEncryptor{}
	dec := newStubDecryptor()

	// Encrypt the SAME plaintext for two distinct resources in the same
	// deployment. The stub Encryptor stores plaintext keyed by AAD so we
	// can prove the AAD differs.
	rowA := &sampleWithSibling{UserID: "id_A", Email: "secret@example.com", Note: "A"}
	if err := crypto.EncryptPIIFieldsStrict(context.Background(), enc, "dep_X", "channel", "id_A", rowA); err != nil {
		t.Fatalf("encrypt A: %v", err)
	}
	dec.store["dep_X|channel|id_A|Email"] = []byte("secret@example.com")

	rowB := &sampleWithSibling{UserID: "id_B", Email: "secret@example.com", Note: "B"}
	if err := crypto.EncryptPIIFieldsStrict(context.Background(), enc, "dep_X", "channel", "id_B", rowB); err != nil {
		t.Fatalf("encrypt B: %v", err)
	}
	dec.store["dep_X|channel|id_B|Email"] = []byte("secret@example.com")

	// Sanity: the round-trip on rowA's own envelope succeeds.
	aadA := crypto.FieldAAD("dep_X", "channel", "id_A", "Email")
	if _, err := dec.DecryptField(context.Background(), rowA.EmailEnvelope, "dep_X", aadA); err != nil {
		t.Fatalf("decrypt A under its own AAD must succeed, got %v", err)
	}

	// The attack: swap rowA's ciphertext into rowB's read path. Same kid
	// (deployment_id), same field name, but the AAD now carries id_B. The
	// AEAD verify MUST fail — not silently return the plaintext.
	aadB := crypto.FieldAAD("dep_X", "channel", "id_B", "Email")
	if _, err := dec.DecryptField(context.Background(), rowA.EmailEnvelope, "dep_X", aadB); err == nil {
		t.Fatalf("cross-resource AAD swap MUST be rejected by AEAD; decrypt unexpectedly succeeded")
	}
}
