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
