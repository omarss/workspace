package apikey_test

import (
	"errors"
	"strings"
	"testing"

	"github.com/omarss/ivr/internal/tenant/apikey"
)

func TestGenerate_WellFormed(t *testing.T) {
	k, err := apikey.Generate()
	if err != nil {
		t.Fatalf("Generate: %v", err)
	}
	if k.KID == "" {
		t.Error("KID empty")
	}
	if k.Secret == "" {
		t.Error("Secret empty")
	}
	if k.Token != k.KID+"."+k.Secret {
		t.Errorf("Token = %q want %q", k.Token, k.KID+"."+k.Secret)
	}
	if !strings.HasPrefix(k.Token, "ivr_") {
		t.Errorf("Token missing prefix: %q", k.Token)
	}
}

func TestGenerate_KIDIsStable(t *testing.T) {
	const want = 16 // ivr_ + 12 chars of base32
	for range 32 {
		k, _ := apikey.Generate()
		if len(k.KID) != want {
			t.Fatalf("len(KID)=%d want %d (kid=%q)", len(k.KID), want, k.KID)
		}
	}
}

func TestGenerate_UnpredictableSecrets(t *testing.T) {
	seen := map[string]bool{}
	const n = 1000
	for range n {
		k, _ := apikey.Generate()
		if seen[k.Secret] {
			t.Fatalf("collision in %d generations", n)
		}
		seen[k.Secret] = true
	}
	if len(seen) != n {
		t.Fatalf("got %d unique secrets, want %d", len(seen), n)
	}
}

func TestHash_FormatIsArgon2idPHC(t *testing.T) {
	h, err := apikey.Hash("hunter2")
	if err != nil {
		t.Fatalf("Hash: %v", err)
	}
	if !strings.HasPrefix(h, "$argon2id$v=19$") {
		t.Fatalf("unexpected format: %q", h)
	}
	parts := strings.Split(h, "$")
	if len(parts) != 6 {
		t.Fatalf("expected 6 PHC sections, got %d in %q", len(parts), h)
	}
}

func TestHash_NewSaltEachCall(t *testing.T) {
	a, _ := apikey.Hash("same-secret")
	b, _ := apikey.Hash("same-secret")
	if a == b {
		t.Fatal("same secret hashed twice produced identical strings (no salt?)")
	}
}

func TestVerify_Roundtrip(t *testing.T) {
	h, _ := apikey.Hash("correct-horse-battery-staple")
	ok, err := apikey.Verify("correct-horse-battery-staple", h)
	if err != nil || !ok {
		t.Fatalf("Verify ok=%v err=%v", ok, err)
	}
}

func TestVerify_RejectsWrongSecret(t *testing.T) {
	h, _ := apikey.Hash("right")
	ok, _ := apikey.Verify("wrong", h)
	if ok {
		t.Fatal("Verify accepted wrong secret")
	}
}

func TestVerify_RejectsTamperedHash(t *testing.T) {
	h, _ := apikey.Hash("right")
	tampered := h[:len(h)-2] + "AA"
	ok, _ := apikey.Verify("right", tampered)
	if ok {
		t.Fatal("Verify accepted tampered hash")
	}
}

func TestVerify_RejectsMalformedHash(t *testing.T) {
	cases := []string{
		"",
		"not-a-hash",
		"$argon2id$v=19$$$",
		"$bcrypt$v=2$$$",
		"$argon2id$v=19$m=65536,t=3,p=2$YWJjZA$",
	}
	for _, h := range cases {
		_, err := apikey.Verify("any", h)
		if err == nil {
			t.Errorf("expected error for malformed hash %q", h)
		}
	}
}

func TestSplitToken_Roundtrip(t *testing.T) {
	k, _ := apikey.Generate()
	kid, secret, err := apikey.SplitToken(k.Token)
	if err != nil {
		t.Fatalf("SplitToken: %v", err)
	}
	if kid != k.KID || secret != k.Secret {
		t.Fatalf("split mismatch: kid=%q want %q, secret=%q want %q", kid, k.KID, secret, k.Secret)
	}
}

func TestSplitToken_RejectsMalformed(t *testing.T) {
	cases := []string{
		"",
		"missing-dot",
		"too.many.dots",
		".onlysecret",
		"onlykid.",
		"foo.bar", // no ivr_ prefix
	}
	for _, tok := range cases {
		_, _, err := apikey.SplitToken(tok)
		if !errors.Is(err, apikey.ErrMalformedToken) {
			t.Errorf("token %q: expected ErrMalformedToken, got %v", tok, err)
		}
	}
}

func TestHash_RejectsEmptySecret(t *testing.T) {
	_, err := apikey.Hash("")
	if !errors.Is(err, apikey.ErrEmptySecret) {
		t.Fatalf("expected ErrEmptySecret, got %v", err)
	}
}
