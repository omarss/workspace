package apikeys_test

import (
	"strings"
	"testing"

	"github.com/omarss/saas/internal/dataplane/apikeys"
)

// TestHashSecret_PHCShape pins the canonical OWASP 2024 PHC string.
func TestHashSecret_PHCShape(t *testing.T) {
	phc, err := apikeys.HashSecret("super-secret-token")
	if err != nil {
		t.Fatalf("hash: %v", err)
	}
	if !strings.HasPrefix(phc, "$argon2id$v=19$m=19456,t=2,p=1$") {
		t.Fatalf("PHC prefix wrong: %q", phc)
	}
}

// TestVerifySecret_RoundTrip asserts a fresh hash verifies against the
// original plaintext, and a wrong plaintext does not.
func TestVerifySecret_RoundTrip(t *testing.T) {
	phc, err := apikeys.HashSecret("alpha")
	if err != nil {
		t.Fatalf("hash: %v", err)
	}
	ok, err := apikeys.VerifySecret("alpha", phc)
	if err != nil || !ok {
		t.Fatalf("verify true mismatch: ok=%v err=%v", ok, err)
	}
	ok, err = apikeys.VerifySecret("beta", phc)
	if err != nil {
		t.Fatalf("verify false err: %v", err)
	}
	if ok {
		t.Fatal("verify of wrong plaintext returned true")
	}
}

// TestVerifySecret_MalformedPHC asserts a corrupted PHC returns an
// error, not a silent false.
func TestVerifySecret_MalformedPHC(t *testing.T) {
	_, err := apikeys.VerifySecret("alpha", "not-a-phc")
	if err == nil {
		t.Fatal("expected error for malformed PHC")
	}
}

// TestNewSecret_Shape asserts the bearer + visible prefix lengths
// pinned in the ADR.
func TestNewSecret_Shape(t *testing.T) {
	sec, err := apikeys.NewSecret(apikeys.EnvironmentLive)
	if err != nil {
		t.Fatalf("NewSecret: %v", err)
	}
	if !strings.HasPrefix(sec.Plaintext, "live_") {
		t.Fatalf("plaintext missing env hint: %q", sec.Plaintext)
	}
	if !strings.HasPrefix(sec.Prefix, "live_") || len(sec.Prefix) != len("live_")+apikeys.PrefixRandomLen {
		t.Fatalf("prefix wrong shape: %q", sec.Prefix)
	}
	// Underscores must split the plaintext into three non-empty parts.
	parts := strings.Split(sec.Plaintext, "_")
	if len(parts) != 3 || len(parts[2]) != apikeys.SecretRandomLen {
		t.Fatalf("plaintext shape mismatch: %q", sec.Plaintext)
	}
}

// TestParseBearer asserts the parser rejects malformed shapes and
// accepts the canonical one.
func TestParseBearer(t *testing.T) {
	sec, _ := apikeys.NewSecret(apikeys.EnvironmentLive)
	env, prefix, secret, err := apikeys.ParseBearer(sec.Plaintext)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if env != apikeys.EnvironmentLive {
		t.Fatalf("env: %q", env)
	}
	if prefix != sec.Prefix {
		t.Fatalf("prefix: %q != %q", prefix, sec.Prefix)
	}
	if secret != sec.Plaintext {
		t.Fatalf("secret should round-trip the full bearer")
	}
	if _, _, _, err := apikeys.ParseBearer("not_a_key"); err == nil {
		t.Fatal("expected ErrBearerMalformed for 2-part bearer")
	}
	if _, _, _, err := apikeys.ParseBearer("bad_AX9BC7D3_short"); err == nil {
		t.Fatal("expected ErrBearerMalformed for bad env")
	}
}

// TestValidateScope pins the resource_type.action shape.
func TestValidateScope(t *testing.T) {
	good := []string{"tenant.read", "api_key.write", "audit.read"}
	for _, sc := range good {
		if err := apikeys.ValidateScope(sc); err != nil {
			t.Fatalf("%q: %v", sc, err)
		}
	}
	bad := []string{"", "tenant", "tenant.", ".write", "Tenant.Read", "tenant/read"}
	for _, sc := range bad {
		if err := apikeys.ValidateScope(sc); err == nil {
			t.Fatalf("expected %q invalid", sc)
		}
	}
}
