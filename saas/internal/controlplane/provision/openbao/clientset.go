package openbao

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"

	bao "github.com/openbao/openbao/api/v2"
)

// ClientConfig is the minimum set of inputs the host adapter needs to
// build an authenticated OpenBao client. The shape mirrors the Phase 4
// envelope.Options structure on purpose — the same operator-facing
// concerns apply (token vs AppRole, CA cert path, address) and we want
// the saasctl debug flags to feel familiar.
type ClientConfig struct {
	// Address is the OpenBao listener URL ("http://127.0.0.1:8200"
	// locally; "https://openbao.svc:8200" in cluster).
	Address string

	// CACertPath is the PEM-encoded CA bundle for TLS verification.
	// Optional; required only when Address is https://.
	CACertPath string

	// Token authenticates directly with a static client token. Mutually
	// exclusive with the AppRole fields. The CP-8 verification flow
	// uses this with the root token read from /openbao/secrets/init.json
	// (which is the dev-only path documented in ADR 006); production
	// flows MUST use the AppRole branch.
	Token string

	// TokenFile lets the operator point at a JSON or plain-text file
	// rather than passing the token on the command line (which leaks
	// to shell history). For .json files we parse the dev init.json
	// shape and extract `root_token`; for any other extension we treat
	// the file content as the raw token after trimming whitespace.
	TokenFile string

	// AppRole credentials. Either both RoleID and SecretID are set
	// (production) or neither is (token branch wins).
	AppRoleRoleID   string
	AppRoleSecretID string
}

// NewClient constructs an authenticated *bao.Client per the supplied
// ClientConfig. Exactly one of Token / TokenFile / AppRole(RoleID +
// SecretID) must be set; the helper rejects ambiguous combinations
// rather than silently picking a precedence.
func NewClient(ctx context.Context, cfg ClientConfig) (*bao.Client, error) {
	if cfg.Address == "" {
		return nil, errors.New("openbao: ClientConfig.Address is required")
	}

	authModes := 0
	if cfg.Token != "" {
		authModes++
	}
	if cfg.TokenFile != "" {
		authModes++
	}
	if cfg.AppRoleRoleID != "" || cfg.AppRoleSecretID != "" {
		authModes++
	}
	if authModes == 0 {
		return nil, errors.New("openbao: ClientConfig requires Token / TokenFile / AppRole credentials")
	}
	if authModes > 1 {
		return nil, errors.New("openbao: ClientConfig must set exactly one of Token / TokenFile / AppRole")
	}

	baoCfg := bao.DefaultConfig()
	baoCfg.Address = cfg.Address
	if cfg.CACertPath != "" {
		if err := baoCfg.ConfigureTLS(&bao.TLSConfig{CACert: cfg.CACertPath}); err != nil {
			return nil, fmt.Errorf("openbao: configure TLS: %w", err)
		}
	}
	bc, err := bao.NewClient(baoCfg)
	if err != nil {
		return nil, fmt.Errorf("openbao: new client: %w", err)
	}

	switch {
	case cfg.Token != "":
		bc.SetToken(cfg.Token)
	case cfg.TokenFile != "":
		token, err := readTokenFile(cfg.TokenFile)
		if err != nil {
			return nil, err
		}
		bc.SetToken(token)
	default:
		// AppRole login.
		if cfg.AppRoleRoleID == "" || cfg.AppRoleSecretID == "" {
			return nil, errors.New("openbao: AppRole requires both RoleID and SecretID")
		}
		sec, err := bc.Logical().WriteWithContext(ctx, "auth/approle/login", map[string]any{
			"role_id":   cfg.AppRoleRoleID,
			"secret_id": cfg.AppRoleSecretID,
		})
		if err != nil {
			return nil, fmt.Errorf("openbao: approle login: %w", err)
		}
		if sec == nil || sec.Auth == nil || sec.Auth.ClientToken == "" {
			return nil, errors.New("openbao: approle login returned no client token")
		}
		bc.SetToken(sec.Auth.ClientToken)
	}

	return bc, nil
}

// readTokenFile loads the token from either a JSON init.json (dev path)
// or a raw text file. Done with a tiny hand-rolled JSON token search
// rather than encoding/json because the dev init.json is large and we
// only need one field — the same approach Phase 4's entrypoint.sh uses
// inside the busybox container.
func readTokenFile(path string) (string, error) {
	raw, err := os.ReadFile(path) // #nosec G304 — operator-supplied path
	if err != nil {
		return "", fmt.Errorf("openbao: read token file %q: %w", path, err)
	}
	s := strings.TrimSpace(string(raw))
	if s == "" {
		return "", fmt.Errorf("openbao: token file %q is empty", path)
	}
	// Heuristic: if the file starts with '{' it's the dev init.json;
	// otherwise treat the content as a raw token. The JSON branch is
	// extracted with a substring scan around the literal "root_token"
	// key — robust to whitespace and trailing fields.
	if s[0] != '{' {
		return s, nil
	}
	idx := strings.Index(s, `"root_token"`)
	if idx < 0 {
		return "", fmt.Errorf("openbao: token file %q is JSON but has no root_token field", path)
	}
	rest := s[idx+len(`"root_token"`):]
	colon := strings.Index(rest, ":")
	if colon < 0 {
		return "", fmt.Errorf("openbao: token file %q malformed near root_token", path)
	}
	rest = rest[colon+1:]
	quoteStart := strings.Index(rest, `"`)
	if quoteStart < 0 {
		return "", fmt.Errorf("openbao: token file %q malformed near root_token value", path)
	}
	rest = rest[quoteStart+1:]
	quoteEnd := strings.Index(rest, `"`)
	if quoteEnd < 0 {
		return "", fmt.Errorf("openbao: token file %q has unterminated root_token value", path)
	}
	return rest[:quoteEnd], nil
}
