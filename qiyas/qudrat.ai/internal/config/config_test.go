package config

import (
	"net/http"
	"strings"
	"testing"
	"time"
)

// clearEnv unsets every QUDRAT_* the loader looks at. t.Setenv handles
// restoration; this just gives us a known baseline per test.
func clearEnv(t *testing.T) {
	t.Helper()
	keys := []string{
		"QUDRAT_HTTP_ADDR", "QUDRAT_HTTP_PORT", "QUDRAT_READ_HEADER_TIMEOUT",
		"QUDRAT_VERSION", "QUDRAT_DATABASE_DSN", "QUDRAT_QUESTIONS_DIR",
		"QUDRAT_OTP_TTL", "QUDRAT_SESSION_TTL",
		"QUDRAT_COOKIE_NAME", "QUDRAT_COOKIE_DOMAIN", "QUDRAT_COOKIE_SECURE",
		"QUDRAT_RESEND_API_KEY", "QUDRAT_RESEND_FROM",
		"QUDRAT_TWILIO_ACCOUNT_SID", "QUDRAT_TWILIO_AUTH_TOKEN",
		"QUDRAT_TWILIO_VERIFY_SERVICE_SID",
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
	if !strings.Contains(cfg.DatabaseDSN, "127.0.0.1:55433") {
		t.Errorf("DatabaseDSN default should target dev container, got %q", cfg.DatabaseDSN)
	}
	if cfg.QuestionsDir != "../questions" {
		t.Errorf("QuestionsDir default: %q", cfg.QuestionsDir)
	}
	if cfg.OTPTTL != 10*time.Minute {
		t.Errorf("OTPTTL default: %v", cfg.OTPTTL)
	}
	if cfg.SessionTTL != 30*24*time.Hour {
		t.Errorf("SessionTTL default: %v", cfg.SessionTTL)
	}
	if cfg.CookieName != "qudrat_session" {
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
	t.Setenv("QUDRAT_HTTP_PORT", "9090")
	t.Setenv("QUDRAT_READ_HEADER_TIMEOUT", "12s")
	t.Setenv("QUDRAT_VERSION", "abc123")
	t.Setenv("QUDRAT_OTP_TTL", "5m")
	t.Setenv("QUDRAT_SESSION_TTL", "168h")
	t.Setenv("QUDRAT_COOKIE_DOMAIN", "qudrat.example.com")
	t.Setenv("QUDRAT_COOKIE_SECURE", "true")
	t.Setenv("QUDRAT_QUESTIONS_DIR", "/tmp/qs")

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
	if cfg.CookieDomain != "qudrat.example.com" {
		t.Errorf("CookieDomain: %q", cfg.CookieDomain)
	}
	if !cfg.CookieSecure {
		t.Errorf("CookieSecure should be true")
	}
	if cfg.QuestionsDir != "/tmp/qs" {
		t.Errorf("QuestionsDir: %q", cfg.QuestionsDir)
	}
}

func TestLoad_RejectsBadDuration(t *testing.T) {
	clearEnv(t)
	t.Setenv("QUDRAT_READ_HEADER_TIMEOUT", "not-a-duration")
	if _, err := Load(); err == nil {
		t.Fatalf("expected error for bad duration")
	}
}

func TestLoad_RejectsBadPort(t *testing.T) {
	clearEnv(t)
	t.Setenv("QUDRAT_HTTP_PORT", "not-a-number")
	if _, err := Load(); err == nil {
		t.Fatalf("expected error for bad port")
	}
}

func TestLoad_PartialTwilio_Rejected(t *testing.T) {
	clearEnv(t)
	t.Setenv("QUDRAT_TWILIO_ACCOUNT_SID", "AC1")
	if _, err := Load(); err == nil {
		t.Fatalf("expected error for partial Twilio config")
	}
}

func TestLoad_FullTwilio_Accepted(t *testing.T) {
	clearEnv(t)
	t.Setenv("QUDRAT_TWILIO_ACCOUNT_SID", "AC1")
	t.Setenv("QUDRAT_TWILIO_AUTH_TOKEN", "secret")
	t.Setenv("QUDRAT_TWILIO_VERIFY_SERVICE_SID", "VAxyz")
	cfg, err := Load()
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if cfg.TwilioAccountSID != "AC1" || cfg.TwilioAuthToken != "secret" || cfg.TwilioVerifyServiceSID != "VAxyz" {
		t.Errorf("twilio creds not applied: %+v", cfg)
	}
}
