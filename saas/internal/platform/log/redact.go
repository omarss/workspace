// Package log centralises the platform's slog handler and PII / secret
// redaction logic. CLAUDE.md project rule: "Never log secrets. The redactor
// list lives in internal/platform/log/redact.go." Add to staticRedactedKeys
// whenever a new sensitive concept lands; codegen + OpenAPI x-pii also feed
// into the dynamic keyset.
//
// The slog handler installed by New() applies the redactor via a
// ReplaceAttr hook AND walks struct values reflectively for pii:"true" /
// sensitive:"true" tags (see scrub_struct.go and ADR 004).
package log

import (
	"strings"
	"sync"
)

// staticRedactedKeys lists field names always redacted regardless of struct
// tags. Per CLAUDE.md, this is the authoritative list — keep it sorted and
// add a comment for any non-obvious entry.
var staticRedactedKeys = map[string]struct{}{
	// HTTP headers carrying credentials.
	"authorization": {},
	"cookie":        {},
	"set-cookie":    {},
	// Generic secret names.
	"password":       {},
	"secret":         {},
	"token":          {},
	"access_token":   {},
	"refresh_token":  {},
	"client_secret":  {},
	"webhook_secret": {},
	// API keys.
	"api_key":        {},
	"api_key_secret": {},
	// OpenBao / Vault material — see AGENTS.md §18.7 + foundations §5.
	"bao_token":     {},
	"vault_token":   {},
	"unseal_share":  {},
	"wrapped_dek":   {},
	"dek_plaintext": {},
	// Notification BYOK creds — see ADR 017.
	"smtp_password":         {},
	"sendgrid_api_key":      {},
	"ses_secret_access_key": {},
}

var (
	dynamicMu   sync.RWMutex
	dynamicKeys = map[string]struct{}{}
)

// RegisterRedactedKey adds k to the dynamic redaction set. Called from
// init() funcs in oapi-codegen-generated packages that scan
// x-oapi-codegen-extra-tags { pii: "true" } markers, and from manual
// registrations when a sensitive field cannot be expressed in OpenAPI.
func RegisterRedactedKey(k string) {
	dynamicMu.Lock()
	defer dynamicMu.Unlock()
	dynamicKeys[strings.ToLower(k)] = struct{}{}
}

// IsRedactedKey reports whether k matches the static or dynamic redactor
// keysets. Case-insensitive.
func IsRedactedKey(k string) bool {
	k = strings.ToLower(k)
	if _, ok := staticRedactedKeys[k]; ok {
		return true
	}
	dynamicMu.RLock()
	defer dynamicMu.RUnlock()
	_, ok := dynamicKeys[k]
	return ok
}
