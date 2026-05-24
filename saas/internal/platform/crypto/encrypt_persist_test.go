package crypto_test

import (
	"context"
	"errors"
	"testing"

	"github.com/omarss/saas/internal/platform/crypto"
)

type stubEncryptor struct {
	called []string
}

func (s *stubEncryptor) EncryptField(_ context.Context, _ string, _ []byte, aad []byte) (crypto.Envelope, error) {
	s.called = append(s.called, string(aad))
	return crypto.Envelope{Ciphertext: []byte("ct"), KID: "kid"}, nil
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
	if err := crypto.EncryptPIIFields(context.Background(), enc, "kid", v); err != nil {
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
}

func TestEncryptPIIFields_NotPointer(t *testing.T) {
	enc := &stubEncryptor{}
	err := crypto.EncryptPIIFields(context.Background(), enc, "kid", sample{Email: "x@y"})
	if !errors.Is(err, crypto.ErrNotPointer) {
		t.Fatalf("expected ErrNotPointer, got %v", err)
	}
}

func TestEncryptPIIFields_NoEncryptor(t *testing.T) {
	err := crypto.EncryptPIIFields(context.Background(), nil, "kid", &sample{})
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
	if err := crypto.EncryptPIIFields(context.Background(), enc, "kid", v); err != nil {
		t.Fatalf("EncryptPIIFields: %v", err)
	}
	if v.Email != "" {
		t.Errorf("plaintext Email not cleared: %q", v.Email)
	}
	if string(v.EmailEnvelope.Ciphertext) != "ct" || v.EmailEnvelope.KID != "kid" {
		t.Errorf("sibling envelope not populated: %+v", v.EmailEnvelope)
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
	err := crypto.EncryptPIIFieldsStrict(context.Background(), enc, "kid", v)
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
	if err := crypto.EncryptPIIFieldsStrict(context.Background(), enc, "kid", v); err != nil {
		t.Fatalf("EncryptPIIFieldsStrict: %v", err)
	}
	if v.Email != "" {
		t.Errorf("plaintext Email not cleared: %q", v.Email)
	}
	if string(v.EmailEnvelope.Ciphertext) != "ct" || v.EmailEnvelope.KID != "kid" {
		t.Errorf("sibling envelope not populated: %+v", v.EmailEnvelope)
	}
}
