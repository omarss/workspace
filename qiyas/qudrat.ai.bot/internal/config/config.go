// Package config loads runtime settings from the process environment.
//
// All settings have safe defaults for local dev. Production values come
// from the k8s secret. The loader never panics — callers decide whether
// a missing required value is fatal.
package config

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

// Config bundles every runtime setting the bot binary needs.
type Config struct {
	HTTPAddr          string
	ReadHeaderTimeout time.Duration
	Version           string

	// QudratAPIURL is the base URL of the qudrat-api service.
	QudratAPIURL string
	// BotAuthToken is the shared secret with qudrat-api for /api/auth/external.
	BotAuthToken string

	// Telegram. Empty token disables the transport.
	TelegramToken string

	// Twilio (WhatsApp). Empty SID disables the transport.
	TwilioAccountSID string
	TwilioAuthToken  string
	TwilioFrom       string // e.g. "whatsapp:+14155238886"
}

// Load reads the config from the environment.
func Load() (Config, error) {
	cfg := Config{
		HTTPAddr:          envOr("QUDRAT_BOT_HTTP_ADDR", ":8081"),
		ReadHeaderTimeout: 5 * time.Second,
		Version:           envOr("QUDRAT_BOT_VERSION", "dev"),
		QudratAPIURL:      envOr("QUDRAT_API_URL", "http://127.0.0.1:8080"),
		BotAuthToken:      os.Getenv("QUDRAT_BOT_AUTH_TOKEN"),
		TelegramToken:     os.Getenv("QUDRAT_BOT_TELEGRAM_TOKEN"),
		TwilioAccountSID:  os.Getenv("QUDRAT_BOT_TWILIO_ACCOUNT_SID"),
		TwilioAuthToken:   os.Getenv("QUDRAT_BOT_TWILIO_AUTH_TOKEN"),
		TwilioFrom:        os.Getenv("QUDRAT_BOT_TWILIO_FROM"),
	}

	if raw := os.Getenv("QUDRAT_BOT_HTTP_PORT"); raw != "" {
		if _, err := strconv.Atoi(raw); err != nil {
			return Config{}, fmt.Errorf("QUDRAT_BOT_HTTP_PORT: %w", err)
		}
		cfg.HTTPAddr = ":" + raw
	}
	if raw := os.Getenv("QUDRAT_BOT_READ_HEADER_TIMEOUT"); raw != "" {
		d, err := time.ParseDuration(raw)
		if err != nil {
			return Config{}, fmt.Errorf("QUDRAT_BOT_READ_HEADER_TIMEOUT: %w", err)
		}
		cfg.ReadHeaderTimeout = d
	}
	if (cfg.TwilioAccountSID != "" || cfg.TwilioAuthToken != "" || cfg.TwilioFrom != "") &&
		(cfg.TwilioAccountSID == "" || cfg.TwilioAuthToken == "" || cfg.TwilioFrom == "") {
		return Config{}, fmt.Errorf("twilio config is partial; set all three of ACCOUNT_SID, AUTH_TOKEN, FROM")
	}
	return cfg, nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
