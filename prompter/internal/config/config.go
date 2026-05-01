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

	// OTPTTL is how long an OTP challenge stays valid. Default 10m.
	OTPTTL time.Duration
	// SessionTTL is how long a refresh-token session stays valid. Default 30d.
	SessionTTL time.Duration

	// Cookie attributes. CookieDomain is empty in dev so the cookie pins to
	// the current host; production sets it to "prompter.omarss.net".
	CookieName     string
	CookieDomain   string
	CookieSecure   bool
	CookieSameSite http.SameSite

	// Email OTP delivery. Empty key falls back to dev logging.
	ResendAPIKey string
	// ResendFrom must be a verified sender, e.g.
	// "prompter <noreply@omarss.net>". Required if ResendAPIKey is set.
	ResendFrom string

	// SMS OTP via Twilio Verify. Empty SID falls back to dev fixed-code.
	TwilioAccountSID       string
	TwilioAuthToken        string
	TwilioVerifyServiceSID string

	// Together.ai inference API key. Empty in dev means model listing works
	// but actual prompt runs will fail at the provider boundary — fine for
	// validating the surface, not enough to play the game.
	TogetherAPIKey string
}

// Load reads the config from the environment. Unknown values fall back to
// defaults. An error is returned only when an explicitly set value is
// malformed.
func Load() (Config, error) {
	cfg := Config{
		HTTPAddr:          envOr("PROMPTER_HTTP_ADDR", ":8080"),
		ReadHeaderTimeout: 5 * time.Second,
		Version:           envOr("PROMPTER_VERSION", "dev"),
		DatabaseDSN: envOr("PROMPTER_DATABASE_DSN",
			"postgres://prompter:prompter-dev@127.0.0.1:55432/prompter?sslmode=disable"),
		OTPTTL:         10 * time.Minute,
		SessionTTL:     30 * 24 * time.Hour,
		CookieName:     envOr("PROMPTER_COOKIE_NAME", "prompter_session"),
		CookieDomain:   os.Getenv("PROMPTER_COOKIE_DOMAIN"),
		CookieSecure:   os.Getenv("PROMPTER_COOKIE_SECURE") == "true",
		CookieSameSite: http.SameSiteLaxMode,

		ResendAPIKey: os.Getenv("PROMPTER_RESEND_API_KEY"),
		ResendFrom: envOr("PROMPTER_RESEND_FROM",
			"prompter <noreply@example.invalid>"),

		TwilioAccountSID:       os.Getenv("PROMPTER_TWILIO_ACCOUNT_SID"),
		TwilioAuthToken:        os.Getenv("PROMPTER_TWILIO_AUTH_TOKEN"),
		TwilioVerifyServiceSID: os.Getenv("PROMPTER_TWILIO_VERIFY_SERVICE_SID"),

		TogetherAPIKey: os.Getenv("PROMPTER_TOGETHER_API_KEY"),
	}

	if raw := os.Getenv("PROMPTER_READ_HEADER_TIMEOUT"); raw != "" {
		d, err := time.ParseDuration(raw)
		if err != nil {
			return Config{}, fmt.Errorf("PROMPTER_READ_HEADER_TIMEOUT: %w", err)
		}
		cfg.ReadHeaderTimeout = d
	}
	if raw := os.Getenv("PROMPTER_HTTP_PORT"); raw != "" {
		if _, err := strconv.Atoi(raw); err != nil {
			return Config{}, fmt.Errorf("PROMPTER_HTTP_PORT: %w", err)
		}
		cfg.HTTPAddr = ":" + raw
	}
	if raw := os.Getenv("PROMPTER_OTP_TTL"); raw != "" {
		d, err := time.ParseDuration(raw)
		if err != nil {
			return Config{}, fmt.Errorf("PROMPTER_OTP_TTL: %w", err)
		}
		cfg.OTPTTL = d
	}
	if raw := os.Getenv("PROMPTER_SESSION_TTL"); raw != "" {
		d, err := time.ParseDuration(raw)
		if err != nil {
			return Config{}, fmt.Errorf("PROMPTER_SESSION_TTL: %w", err)
		}
		cfg.SessionTTL = d
	}

	if cfg.ResendAPIKey != "" && cfg.ResendFrom == "" {
		return Config{}, fmt.Errorf("PROMPTER_RESEND_FROM is required when PROMPTER_RESEND_API_KEY is set")
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
