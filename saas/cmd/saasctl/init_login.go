// Phase 15 — `operator-login` step for saasctl init.
//
// The real PKCE flow (browser-based authorization code with PKCE
// against the operators realm) is deferred until the gocloak admin
// client wiring lands; see ADR 020 §Deferred. Until then, the wizard
// accepts a pre-obtained bearer token via --operator-token-file and
// stashes it in ~/.saas/credentials.json so subsequent saasctl
// commands can pick it up.
//
// When the flag is absent AND no cached credentials exist, the step
// emits a clear "PKCE deferred — pass --operator-token-file or use
// mock headers" message and continues — the provision step falls back
// to the X-Mock-Operator-* headers in local-dev.

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// credentialsPath is the on-disk cache used by saasctl commands to pick
// up the operator bearer token without re-running the wizard.
func credentialsPath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("resolve home directory: %w", err)
	}
	return filepath.Join(home, ".saas", "credentials.json"), nil
}

// operatorCredentials is the saved-token shape. We keep it open-ended
// so the eventual PKCE flow can add refresh_token / id_token / expiry
// without a schema migration.
type operatorCredentials struct {
	Token     string `json:"token"`
	Issued    string `json:"issued_at,omitempty"`
	ExpiresAt string `json:"expires_at,omitempty"`
	Source    string `json:"source,omitempty"`
}

func runOperatorLogin(ctx context.Context, cfg *initConfig) (string, error) {
	if cfg.OperatorTokenFn != "" {
		raw, err := os.ReadFile(cfg.OperatorTokenFn) // #nosec G304 — operator-supplied --operator-token-file path
		if err != nil {
			return "", fmt.Errorf("read operator token file: %w", err)
		}
		token := strings.TrimSpace(string(raw))
		if token == "" {
			return "", fmt.Errorf("operator token file %q is empty", cfg.OperatorTokenFn)
		}
		if err := writeCredentials(operatorCredentials{
			Token:  token,
			Issued: nowUTC().Format("2006-01-02T15:04:05Z"),
			Source: "operator-token-file",
		}); err != nil {
			return "", err
		}
		return "from file", nil
	}
	// Cached creds short-circuit the step.
	if path, err := credentialsPath(); err == nil {
		if _, err := os.Stat(path); err == nil {
			return "already done", nil
		}
	}
	// No flag, no cache: log a clear note and fall through. The
	// provision step will rely on the mock-operator headers that are
	// already shipped for local dev.
	return "skipped (PKCE deferred — see ADR 020)", nil
}

func writeCredentials(c operatorCredentials) error {
	path, err := credentialsPath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("create credential dir: %w", err)
	}
	raw, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal credentials: %w", err)
	}
	// Write with 0600 — the credential file is operator-private.
	if err := os.WriteFile(path, raw, 0o600); err != nil {
		return fmt.Errorf("write credentials: %w", err)
	}
	return nil
}

// readCredentials is the inverse used by saasctl status / saasctl init
// re-runs. Returns the empty credentials when no file exists; an error
// only on read/parse failure.
func readCredentials() (operatorCredentials, error) {
	path, err := credentialsPath()
	if err != nil {
		return operatorCredentials{}, err
	}
	raw, err := os.ReadFile(path) // #nosec G304 — fixed ~/.saas/credentials.json path under the caller's HOME
	if os.IsNotExist(err) {
		return operatorCredentials{}, nil
	}
	if err != nil {
		return operatorCredentials{}, fmt.Errorf("read credentials: %w", err)
	}
	var c operatorCredentials
	if err := json.Unmarshal(raw, &c); err != nil {
		return operatorCredentials{}, fmt.Errorf("parse credentials: %w", err)
	}
	return c, nil
}
