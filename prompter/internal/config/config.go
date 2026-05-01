// Package config loads runtime settings from the process environment.
//
// All settings have safe defaults for local dev. Production overrides come
// from the k8s secret and a non-secret ConfigMap. The loader never panics —
// callers decide whether a missing required value is fatal.
package config

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

// Config bundles every runtime setting the api binary needs. Keep fields
// flat: nested config is harder to surface in env-var docs.
type Config struct {
	// HTTP listen address. Default ":8080".
	HTTPAddr string

	// ReadHeaderTimeout caps how long the server waits for request headers.
	// Default 5s. Hardens against slowloris.
	ReadHeaderTimeout time.Duration

	// Version is the build version, surfaced via /healthz and the index page.
	// Set at build time via -ldflags.
	Version string
}

// Load reads the config from the environment. Unknown values fall back to
// defaults. An error is returned only when an explicitly set value is
// malformed.
func Load() (Config, error) {
	cfg := Config{
		HTTPAddr:          envOr("PROMPTER_HTTP_ADDR", ":8080"),
		ReadHeaderTimeout: 5 * time.Second,
		Version:           envOr("PROMPTER_VERSION", "dev"),
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

	return cfg, nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
