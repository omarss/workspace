// Package config loads runtime settings from the process environment.
//
// All settings have safe defaults for local dev. Production overrides come
// from the k8s secret and a non-secret ConfigMap. The loader never panics —
// callers decide whether a missing required value is fatal.
package config

import (
	"fmt"
	"net/http"
	"os"
	"strconv"
	"time"
)

// Config bundles every runtime setting the api binary needs.
type Config struct {
	// HTTP listen address. Default ":8080".
	HTTPAddr string

	// ReadHeaderTimeout caps how long the server waits for request headers.
	// Default 5s. Hardens against slowloris.
	ReadHeaderTimeout time.Duration

	// Version is the build version, surfaced via /healthz and the index page.
	// Set at build time via -ldflags.
	Version string

	// DatabaseDSN points at host Postgres. Default targets the dev container
	// started by `make db-up`.
	DatabaseDSN string

	// QuestionsDir is where the importer reads `*.json` files from. Default
	// is the sibling `../questions/` directory in the workspace.
	QuestionsDir string

	// OTPTTL is how long an OTP challenge stays valid. Default 10m. Used by
	// auth (Phase 2).
	OTPTTL time.Duration
	// SessionTTL is how long a refresh-token session stays valid. Default
	// 30d. Used by auth (Phase 2).
	SessionTTL time.Duration

	// Cookie attributes. CookieDomain is empty in dev so the cookie pins to
	// the current host; production sets it to "qudrat.omarss.net".
	CookieName     string
	CookieDomain   string
	CookieSecure   bool
	CookieSameSite http.SameSite

	// Email OTP delivery. Empty key falls back to dev logging.
	ResendAPIKey string
	// ResendFrom must be a verified sender, e.g.
	// "qudrat <noreply@omarss.net>". Required if ResendAPIKey is set.
	ResendFrom string

	// SMS OTP via Twilio Verify. Empty SID falls back to dev fixed-code.
	TwilioAccountSID       string
	TwilioAuthToken        string
	TwilioVerifyServiceSID string

	// DevFixedOTP overrides the devlog fixed-code for both SMS and email
	// when the production providers are not configured. Useful for QA on
	// a deployed environment without access to logs. Leave empty in
	// production — the dev paths must NEVER be reachable there.
	DevFixedOTP string
}

// Load reads the config from the environment. Unknown values fall back to
// defaults. An error is returned only when an explicitly set value is
// malformed.
func Load() (Config, error) {
	cfg := Config{
		HTTPAddr:          envOr("QUDRAT_HTTP_ADDR", ":8080"),
		ReadHeaderTimeout: 5 * time.Second,
		Version:           envOr("QUDRAT_VERSION", "dev"),
		DatabaseDSN: envOr("QUDRAT_DATABASE_DSN",
			"postgres://qudrat:qudrat-dev@127.0.0.1:55433/qudrat?sslmode=disable"),
		QuestionsDir:   envOr("QUDRAT_QUESTIONS_DIR", "../questions"),
		OTPTTL:         10 * time.Minute,
		SessionTTL:     30 * 24 * time.Hour,
		CookieName:     envOr("QUDRAT_COOKIE_NAME", "qudrat_session"),
		CookieDomain:   os.Getenv("QUDRAT_COOKIE_DOMAIN"),
		CookieSecure:   os.Getenv("QUDRAT_COOKIE_SECURE") == "true",
		CookieSameSite: http.SameSiteLaxMode,

		ResendAPIKey: os.Getenv("QUDRAT_RESEND_API_KEY"),
		ResendFrom: envOr("QUDRAT_RESEND_FROM",
			"qudrat <noreply@example.invalid>"),

		TwilioAccountSID:       os.Getenv("QUDRAT_TWILIO_ACCOUNT_SID"),
		TwilioAuthToken:        os.Getenv("QUDRAT_TWILIO_AUTH_TOKEN"),
		TwilioVerifyServiceSID: os.Getenv("QUDRAT_TWILIO_VERIFY_SERVICE_SID"),

		DevFixedOTP: os.Getenv("QUDRAT_DEV_FIXED_OTP"),
	}

	if raw := os.Getenv("QUDRAT_READ_HEADER_TIMEOUT"); raw != "" {
		d, err := time.ParseDuration(raw)
		if err != nil {
			return Config{}, fmt.Errorf("QUDRAT_READ_HEADER_TIMEOUT: %w", err)
		}
		cfg.ReadHeaderTimeout = d
	}
	if raw := os.Getenv("QUDRAT_HTTP_PORT"); raw != "" {
		if _, err := strconv.Atoi(raw); err != nil {
			return Config{}, fmt.Errorf("QUDRAT_HTTP_PORT: %w", err)
		}
		cfg.HTTPAddr = ":" + raw
	}
	if raw := os.Getenv("QUDRAT_OTP_TTL"); raw != "" {
		d, err := time.ParseDuration(raw)
		if err != nil {
			return Config{}, fmt.Errorf("QUDRAT_OTP_TTL: %w", err)
		}
		cfg.OTPTTL = d
	}
	if raw := os.Getenv("QUDRAT_SESSION_TTL"); raw != "" {
		d, err := time.ParseDuration(raw)
		if err != nil {
			return Config{}, fmt.Errorf("QUDRAT_SESSION_TTL: %w", err)
		}
		cfg.SessionTTL = d
	}

	if cfg.ResendAPIKey != "" && cfg.ResendFrom == "" {
		return Config{}, fmt.Errorf("QUDRAT_RESEND_FROM is required when QUDRAT_RESEND_API_KEY is set")
	}
	if (cfg.TwilioAccountSID != "" || cfg.TwilioAuthToken != "" || cfg.TwilioVerifyServiceSID != "") &&
		(cfg.TwilioAccountSID == "" || cfg.TwilioAuthToken == "" || cfg.TwilioVerifyServiceSID == "") {
		return Config{}, fmt.Errorf("twilio config is partial; set all three of ACCOUNT_SID, AUTH_TOKEN, VERIFY_SERVICE_SID")
	}

	return cfg, nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
