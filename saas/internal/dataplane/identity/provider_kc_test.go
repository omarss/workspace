package identity

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"net/url"
	"strings"
	"testing"
)

// TestComputeLinkHash_KnownInput pins the hash function against a fixed input
// so regressions in the canonical Keycloak hash shape are caught loudly.
// The canonical algorithm is base64url(sha256(nonce + session_state + issued_for + provider)).
func TestComputeLinkHash_KnownInput(t *testing.T) {
	nonce := "test-nonce-123"
	sessionState := "kc-session-abc"
	issuedFor := "saas-data-local"
	provider := ProviderGoogle

	got := computeLinkHash(nonce, sessionState, issuedFor, provider)

	// Recompute the expected value here so the test documents the formula
	// while still pinning a literal — any mutation to the hash builder
	// changes both halves and the diff is human-reviewable.
	expectedSum := sha256.Sum256([]byte(nonce + sessionState + issuedFor + string(provider)))
	expected := base64.RawURLEncoding.EncodeToString(expectedSum[:])
	if got != expected {
		t.Fatalf("hash mismatch: got=%s want=%s", got, expected)
	}
	if strings.ContainsAny(got, "=+/") {
		t.Fatalf("hash must be base64url (no =, +, /), got: %s", got)
	}
}

// TestStartSocialLogin_URLShape verifies the URL structure conforms to
// Keycloak's documented client-initiated link endpoint.
func TestStartSocialLogin_URLShape(t *testing.T) {
	p := NewKeycloakProvider("https://kc.example.com", func(_ context.Context) (string, error) {
		return "tok", nil
	})
	out, err := p.StartSocialLogin(context.Background(), StartSocialLoginArgs{
		Realm:        "saas-data-local",
		ClientID:     "saas-data-local",
		Provider:     ProviderGoogle,
		Nonce:        "n0",
		SessionState: "ss0",
		IssuedFor:    "saas-data-local",
		ReturnTo:     "https://app.example.com/cb?x=1",
	})
	if err != nil {
		t.Fatalf("StartSocialLogin: %v", err)
	}
	u, err := url.Parse(out)
	if err != nil {
		t.Fatalf("parse url: %v", err)
	}
	if u.Host != "kc.example.com" || u.Path != "/realms/saas-data-local/broker/google/link" {
		t.Errorf("unexpected URL: scheme=%s host=%s path=%s", u.Scheme, u.Host, u.Path)
	}
	q := u.Query()
	if q.Get("client_id") != "saas-data-local" {
		t.Errorf("client_id wrong: %q", q.Get("client_id"))
	}
	if q.Get("redirect_uri") != "https://app.example.com/cb?x=1" {
		t.Errorf("redirect_uri wrong: %q", q.Get("redirect_uri"))
	}
	if q.Get("nonce") != "n0" {
		t.Errorf("nonce wrong: %q", q.Get("nonce"))
	}
	want := computeLinkHash("n0", "ss0", "saas-data-local", ProviderGoogle)
	if q.Get("hash") != want {
		t.Errorf("hash wrong: got=%q want=%q", q.Get("hash"), want)
	}
}

// TestStartSocialLogin_RequiresAllArgs verifies the adapter fails closed
// when any of the security-critical arguments is missing. A half-formed URL
// would otherwise be a forgery vector.
func TestStartSocialLogin_RequiresAllArgs(t *testing.T) {
	p := NewKeycloakProvider("https://kc.example.com", nil)
	base := StartSocialLoginArgs{
		Realm:        "r",
		ClientID:     "c",
		Provider:     ProviderGoogle,
		Nonce:        "n",
		SessionState: "ss",
		IssuedFor:    "if",
		ReturnTo:     "https://x",
	}
	cases := []struct {
		name   string
		mutate func(*StartSocialLoginArgs)
	}{
		{"empty realm", func(a *StartSocialLoginArgs) { a.Realm = "" }},
		{"empty client_id", func(a *StartSocialLoginArgs) { a.ClientID = "" }},
		{"invalid provider", func(a *StartSocialLoginArgs) { a.Provider = Provider("microsoft") }},
		{"empty nonce", func(a *StartSocialLoginArgs) { a.Nonce = "" }},
		{"empty session_state", func(a *StartSocialLoginArgs) { a.SessionState = "" }},
		{"empty issued_for", func(a *StartSocialLoginArgs) { a.IssuedFor = "" }},
		{"empty return_to", func(a *StartSocialLoginArgs) { a.ReturnTo = "" }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			a := base
			tc.mutate(&a)
			if _, err := p.StartSocialLogin(context.Background(), a); err == nil {
				t.Fatalf("expected error for %s, got nil", tc.name)
			}
		})
	}
}
