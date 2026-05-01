package config

import (
	"net/http"
	"strings"
	"testing"
	"time"
)

// clearEnv unsets every PROMPTER_* the loader looks at. t.Setenv handles
// restoration; this just gives us a known baseline per test.
func clearEnv(t *testing.T) {
	t.Helper()
	keys := []string{
		"PROMPTER_HTTP_ADDR", "PROMPTER_HTTP_PORT", "PROMPTER_READ_HEADER_TIMEOUT",
		"PROMPTER_VERSION", "PROMPTER_DATABASE_DSN",
		"PROMPTER_OTP_TTL", "PROMPTER_SESSION_TTL",
		"PROMPTER_COOKIE_NAME", "PROMPTER_COOKIE_DOMAIN", "PROMPTER_COOKIE_SECURE",
		"PROMPTER_RESEND_API_KEY", "PROMPTER_RESEND_FROM",
		"PROMPTER_TWILIO_ACCOUNT_SID", "PROMPTER_TWILIO_AUTH_TOKEN",
		"PROMPTER_TWILIO_VERIFY_SERVICE_SID",
	}
	for _, k := range keys {
		t.Setenv(k, "")
	}
}

func TestLoad_Defaults(t *testing.T) {
	clearEnv(t)

	cfg, err := Load()
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if cfg.HTTPAddr != ":8080" {
		t.Errorf("HTTPAddr: got %q, want :8080", cfg.HTTPAddr)
	}
	if cfg.ReadHeaderTimeout != 5*time.Second {
		t.Errorf("ReadHeaderTimeout: got %v", cfg.ReadHeaderTimeout)
	}
	if cfg.Version != "dev" {
		t.Errorf("Version: got %q", cfg.Version)
	}
	if !strings.Contains(cfg.DatabaseDSN, "127.0.0.1:55432") {
		t.Errorf("DatabaseDSN default should target dev container, got %q", cfg.DatabaseDSN)
	}
	if cfg.OTPTTL != 10*time.Minute {
		t.Errorf("OTPTTL default: %v", cfg.OTPTTL)
	}
	if cfg.SessionTTL != 30*24*time.Hour {
		t.Errorf("SessionTTL default: %v", cfg.SessionTTL)
	}
	if cfg.CookieName != "prompter_session" {
		t.Errorf("CookieName default: %q", cfg.CookieName)
	}
	if cfg.CookieSecure {
		t.Errorf("CookieSecure default should be false")
	}
	if cfg.CookieSameSite != http.SameSiteLaxMode {
		t.Errorf("CookieSameSite default should be Lax")
	}
}

func TestLoad_OverridesFromEnv(t *testing.T) {
	clearEnv(t)
	t.Setenv("PROMPTER_HTTP_PORT", "9090")
	t.Setenv("PROMPTER_READ_HEADER_TIMEOUT", "12s")
	t.Setenv("PROMPTER_VERSION", "abc123")
	t.Setenv("PROMPTER_OTP_TTL", "5m")
	t.Setenv("PROMPTER_SESSION_TTL", "168h")
	t.Setenv("PROMPTER_COOKIE_DOMAIN", "prompter.example.com")
	t.Setenv("PROMPTER_COOKIE_SECURE", "true")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if cfg.HTTPAddr != ":9090" {
		t.Errorf("HTTPAddr: %q", cfg.HTTPAddr)
	}
	if cfg.ReadHeaderTimeout != 12*time.Second {
		t.Errorf("ReadHeaderTimeout: %v", cfg.ReadHeaderTimeout)
	}
	if cfg.Version != "abc123" {
		t.Errorf("Version: %q", cfg.Version)
	}
	if cfg.OTPTTL != 5*time.Minute {
		t.Errorf("OTPTTL: %v", cfg.OTPTTL)
	}
	if cfg.SessionTTL != 168*time.Hour {
		t.Errorf("SessionTTL: %v", cfg.SessionTTL)
	}
	if cfg.CookieDomain != "prompter.example.com" {
		t.Errorf("CookieDomain: %q", cfg.CookieDomain)
	}
	if !cfg.CookieSecure {
		t.Errorf("CookieSecure should be true")
	}
}

func TestLoad_RejectsBadDuration(t *testing.T) {
	clearEnv(t)
	t.Setenv("PROMPTER_READ_HEADER_TIMEOUT", "not-a-duration")
	if _, err := Load(); err == nil {
		t.Fatalf("expected error for bad duration")
	}
}

func TestLoad_RejectsBadPort(t *testing.T) {
	clearEnv(t)
	t.Setenv("PROMPTER_HTTP_PORT", "not-a-number")
	if _, err := Load(); err == nil {
		t.Fatalf("expected error for bad port")
	}
}

func TestLoad_PartialTwilio_Rejected(t *testing.T) {
	clearEnv(t)
	t.Setenv("PROMPTER_TWILIO_ACCOUNT_SID", "AC1")
	// Missing AUTH_TOKEN and VERIFY_SERVICE_SID — must reject.
	if _, err := Load(); err == nil {
		t.Fatalf("expected error for partial Twilio config")
	}
}

func TestLoad_FullTwilio_Accepted(t *testing.T) {
	clearEnv(t)
	t.Setenv("PROMPTER_TWILIO_ACCOUNT_SID", "AC1")
	t.Setenv("PROMPTER_TWILIO_AUTH_TOKEN", "secret")
	t.Setenv("PROMPTER_TWILIO_VERIFY_SERVICE_SID", "VAxyz")
	cfg, err := Load()
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if cfg.TwilioAccountSID != "AC1" || cfg.TwilioAuthToken != "secret" || cfg.TwilioVerifyServiceSID != "VAxyz" {
		t.Errorf("twilio creds not applied: %+v", cfg)
	}
}
