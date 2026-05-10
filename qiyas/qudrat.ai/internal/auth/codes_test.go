package auth

import (
	"errors"
	"strconv"
	"strings"
	"testing"
)

func TestGenerateOTP_Length(t *testing.T) {
	t.Parallel()
	for range 100 {
		code, err := GenerateOTP()
		if err != nil {
			t.Fatalf("generate: %v", err)
		}
		if len(code) != otpDigits {
			t.Fatalf("len(code) = %d, want %d (code=%q)", len(code), otpDigits, code)
		}
		if _, err := strconv.Atoi(code); err != nil {
			t.Fatalf("non-numeric code %q: %v", code, err)
		}
	}
}

func TestGenerateOTP_VariesAcrossCalls(t *testing.T) {
	t.Parallel()
	// Two consecutive identical codes from a 1M-space CSPRNG would be
	// astonishing; sample 50 to make a flake essentially impossible.
	seen := make(map[string]struct{}, 50)
	for range 50 {
		code, err := GenerateOTP()
		if err != nil {
			t.Fatalf("generate: %v", err)
		}
		if _, dup := seen[code]; dup {
			t.Fatalf("duplicate code %q in 50 draws", code)
		}
		seen[code] = struct{}{}
	}
}

func TestHashOTP_VerifyOTP_RoundTrip(t *testing.T) {
	t.Parallel()
	code := "123456"
	hash, err := HashOTP(code)
	if err != nil {
		t.Fatalf("hash: %v", err)
	}
	if !strings.HasPrefix(hash, "$2") {
		t.Fatalf("hash doesn't look like bcrypt: %q", hash)
	}
	if err := VerifyOTP(hash, code); err != nil {
		t.Fatalf("verify: %v", err)
	}
}

func TestVerifyOTP_RejectsWrongCode(t *testing.T) {
	t.Parallel()
	hash, err := HashOTP("000111")
	if err != nil {
		t.Fatalf("hash: %v", err)
	}
	if err := VerifyOTP(hash, "999999"); !errors.Is(err, ErrOTPMismatch) {
		t.Fatalf("got %v, want ErrOTPMismatch", err)
	}
}

func TestVerifyOTP_RejectsMalformedHash(t *testing.T) {
	t.Parallel()
	err := VerifyOTP("not-a-bcrypt-hash", "123456")
	if err == nil {
		t.Fatalf("expected error for malformed hash")
	}
	if errors.Is(err, ErrOTPMismatch) {
		t.Fatalf("malformed hash must not be reported as mismatch (would mask bugs)")
	}
}
