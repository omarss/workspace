package config

import (
	"testing"
	"time"
)

func TestLoad_Defaults(t *testing.T) {
	// Clear env to verify defaults.
	t.Setenv("PROMPTER_HTTP_ADDR", "")
	t.Setenv("PROMPTER_HTTP_PORT", "")
	t.Setenv("PROMPTER_READ_HEADER_TIMEOUT", "")
	t.Setenv("PROMPTER_VERSION", "")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if cfg.HTTPAddr != ":8080" {
		t.Errorf("HTTPAddr: got %q, want :8080", cfg.HTTPAddr)
	}
	if cfg.ReadHeaderTimeout != 5*time.Second {
		t.Errorf("ReadHeaderTimeout: got %v, want 5s", cfg.ReadHeaderTimeout)
	}
	if cfg.Version != "dev" {
		t.Errorf("Version: got %q, want dev", cfg.Version)
	}
}

func TestLoad_OverridesFromEnv(t *testing.T) {
	t.Setenv("PROMPTER_HTTP_PORT", "9090")
	t.Setenv("PROMPTER_READ_HEADER_TIMEOUT", "12s")
	t.Setenv("PROMPTER_VERSION", "abc123")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if cfg.HTTPAddr != ":9090" {
		t.Errorf("HTTPAddr: got %q, want :9090", cfg.HTTPAddr)
	}
	if cfg.ReadHeaderTimeout != 12*time.Second {
		t.Errorf("ReadHeaderTimeout: got %v, want 12s", cfg.ReadHeaderTimeout)
	}
	if cfg.Version != "abc123" {
		t.Errorf("Version: got %q, want abc123", cfg.Version)
	}
}

func TestLoad_RejectsBadDuration(t *testing.T) {
	t.Setenv("PROMPTER_READ_HEADER_TIMEOUT", "not-a-duration")

	if _, err := Load(); err == nil {
		t.Fatalf("expected error for bad duration, got nil")
	}
}

func TestLoad_RejectsBadPort(t *testing.T) {
	t.Setenv("PROMPTER_HTTP_PORT", "not-a-number")

	if _, err := Load(); err == nil {
		t.Fatalf("expected error for bad port, got nil")
	}
}
