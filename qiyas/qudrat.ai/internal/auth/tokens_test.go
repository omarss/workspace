package auth

import (
	"encoding/base64"
	"testing"
)

func TestGenerateSessionToken_Format(t *testing.T) {
	t.Parallel()
	tok, err := GenerateSessionToken()
	if err != nil {
		t.Fatalf("generate: %v", err)
	}
	raw, err := base64.RawURLEncoding.DecodeString(tok)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(raw) != sessionTokenBytes {
		t.Fatalf("len(raw) = %d, want %d", len(raw), sessionTokenBytes)
	}
}

func TestGenerateSessionToken_Unique(t *testing.T) {
	t.Parallel()
	seen := make(map[string]struct{}, 64)
	for range 64 {
		tok, err := GenerateSessionToken()
		if err != nil {
			t.Fatalf("generate: %v", err)
		}
		if _, dup := seen[tok]; dup {
			t.Fatalf("duplicate token from CSPRNG: %q", tok)
		}
		seen[tok] = struct{}{}
	}
}

func TestHashSessionToken_Deterministic(t *testing.T) {
	t.Parallel()
	tok := "abc.def.ghi"
	first := HashSessionToken(tok)
	second := HashSessionToken(tok)
	if first != second {
		t.Fatalf("hash not deterministic: %q vs %q", first, second)
	}
}

func TestHashSessionToken_DistinguishesInputs(t *testing.T) {
	t.Parallel()
	a := HashSessionToken("aaaaaaaa")
	b := HashSessionToken("aaaaaaab")
	if a == b {
		t.Fatalf("collision on adjacent inputs")
	}
}

func TestHashSessionToken_HexLength(t *testing.T) {
	t.Parallel()
	h := HashSessionToken("anything")
	if len(h) != 64 { // sha-256 hex
		t.Fatalf("hex length = %d, want 64 (got %q)", len(h), h)
	}
}
