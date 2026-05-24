package identity

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"errors"
	"strings"
	"sync"

	"github.com/omarss/saas/internal/platform/crypto/envelope"
)

// HMACEmailHasher implements EmailHasher with per-Deployment HMAC keys.
//
// The HMAC key lives in OpenBao KV at
// secret/data/<deployment_id>/identity/email_hmac_key under the field
// "key" (base64-encoded random bytes >= 32 bytes). The key is loaded once
// per process and cached in-memory; rotation is a process restart for
// Phase 5 (live rotation is Phase 12+).
//
// Decision (Phase 5 plan §3): HMAC vs deterministic envelope.
// HMAC is simpler, faster, and does not require a Vault round-trip per
// uniqueness check. Trade-off: rotating the HMAC key requires re-hashing
// every email row. Documented in Phase 5 open questions.
type HMACEmailHasher struct {
	kv *envelope.Client

	mu     sync.Mutex
	cached map[string][]byte // deployment_id -> raw key bytes
}

// NewHMACEmailHasher wraps the envelope KV client. The KV client is
// typically reused from the data-plane envelope client.
func NewHMACEmailHasher(kv *envelope.Client) *HMACEmailHasher {
	return &HMACEmailHasher{kv: kv, cached: map[string][]byte{}}
}

// Normalise lowercases + trims the email. Matches the convention used by
// Keycloak's case-insensitive comparator so the platform's uniqueness check
// agrees with Keycloak's UNIQUE_EMAIL realm setting.
func (h *HMACEmailHasher) Normalise(email string) string {
	return strings.ToLower(strings.TrimSpace(email))
}

// Hash returns HMAC-SHA256(per-deployment-key, normalised-email).
func (h *HMACEmailHasher) Hash(ctx context.Context, deploymentID, email string) ([]byte, error) {
	key, err := h.keyFor(ctx, deploymentID)
	if err != nil {
		return nil, err
	}
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(email))
	return mac.Sum(nil), nil
}

func (h *HMACEmailHasher) keyFor(ctx context.Context, deploymentID string) ([]byte, error) {
	h.mu.Lock()
	if k, ok := h.cached[deploymentID]; ok {
		h.mu.Unlock()
		return k, nil
	}
	h.mu.Unlock()

	if h.kv == nil {
		return nil, errors.New("identity: HMACEmailHasher has no KV client (set SAAS_OPENBAO_DISABLED only if testing)")
	}
	data, err := h.kv.KVGet(ctx, deploymentID, "identity/email_hmac_key")
	if err != nil {
		return nil, err
	}
	raw, ok := data["key"].(string)
	if !ok || raw == "" {
		return nil, errors.New("identity: email_hmac_key missing or wrong type")
	}
	// Stored as raw bytes (KV v2 string fields). Phase 5 stores the key as
	// hex-encoded text on first run; the KV writer is owned by the bootstrap
	// flow (Phase 12 wires the rotation runbook).
	key := []byte(raw)

	h.mu.Lock()
	h.cached[deploymentID] = key
	h.mu.Unlock()
	return key, nil
}

// StaticEmailHasher is a fixed-key hasher for tests + local dev. Production
// MUST use HMACEmailHasher with a per-Deployment KV entry.
type StaticEmailHasher struct{ Key []byte }

// NewStaticEmailHasher returns a hasher backed by an in-memory key. Useful
// for unit tests + the !prod local-dev path.
func NewStaticEmailHasher(key []byte) *StaticEmailHasher {
	if len(key) == 0 {
		// Predictable dev default. NEVER acceptable in prod — the only
		// safeguard is that prod callers must use HMACEmailHasher instead.
		key = []byte("dev-email-hmac-key-do-not-use-in-prod")
	}
	return &StaticEmailHasher{Key: key}
}

// Normalise mirrors HMACEmailHasher.
func (s *StaticEmailHasher) Normalise(email string) string {
	return strings.ToLower(strings.TrimSpace(email))
}

// Hash returns HMAC-SHA256(static-key, email).
func (s *StaticEmailHasher) Hash(_ context.Context, _ string, email string) ([]byte, error) {
	mac := hmac.New(sha256.New, s.Key)
	mac.Write([]byte(email))
	return mac.Sum(nil), nil
}
