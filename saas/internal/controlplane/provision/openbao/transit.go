package openbao

import (
	"context"
	"fmt"

	bao "github.com/openbao/openbao/api/v2"
)

// transitKeyConfig is the production shape per AGENTS.md §18.7 (90-day
// rotation, exportable=false, allow_plaintext_backup=false). The struct
// is private so callers can't tweak fields and silently weaken the key
// posture.
type transitKeyConfig struct {
	keyType              string
	derived              bool
	exportable           bool
	allowPlaintextBackup bool
	autoRotatePeriod     string
}

// defaultTransitKeyConfig is the only acceptable shape for a per-
// Deployment transit key. Phase 4's envelope.EnsureKey writes a similar
// shape; this adapter writes the same fields plus auto_rotate_period
// because §18.7 mandates 90-day rotation and the rotation cadence is
// the key's own property — not something the rotation scheduler has to
// inject later.
var defaultTransitKeyConfig = transitKeyConfig{
	keyType:              "aes256-gcm96",
	derived:              false,
	exportable:           false,
	allowPlaintextBackup: false,
	autoRotatePeriod:     "2160h", // 90 days
}

// EnsureTransitKey writes transit/keys/<kid> with the production shape
// if (and only if) the key does not already exist. Idempotent: the
// pre-read decides whether to write. Re-writing would not corrupt the
// key — OpenBao treats subsequent writes as no-ops for unchanged
// fields — but the pre-read keeps the audit log clean (one entry per
// real provision, not one per Apply retry).
func ensureTransitKey(ctx context.Context, client *bao.Client, kid string) error {
	if kid == "" {
		return fmt.Errorf("%w: kid empty", ErrInvalidInput)
	}

	// Pre-read. ReadWithContext returns (nil, nil) for a missing key
	// (200 with empty data → API client returns nil secret). For an
	// existing key it returns the key metadata.
	sec, err := client.Logical().ReadWithContext(ctx, "transit/keys/"+kid)
	if err != nil {
		return fmt.Errorf("openbao: read transit/keys/%s: %w", kid, err)
	}
	if sec != nil && sec.Data != nil {
		// Belt-and-braces: confirm the existing key is the expected
		// type. A pre-existing aes128-gcm96 key under the same kid
		// would be a security regression — refuse to claim it as ours.
		if t, ok := sec.Data["type"].(string); ok && t != defaultTransitKeyConfig.keyType {
			return fmt.Errorf("%w: transit/keys/%s has type %q, want %q",
				ErrUnexpectedResponse, kid, t, defaultTransitKeyConfig.keyType)
		}
		return nil
	}

	if _, err := client.Logical().WriteWithContext(ctx, "transit/keys/"+kid, map[string]any{
		"type":                   defaultTransitKeyConfig.keyType,
		"derived":                defaultTransitKeyConfig.derived,
		"exportable":             defaultTransitKeyConfig.exportable,
		"allow_plaintext_backup": defaultTransitKeyConfig.allowPlaintextBackup,
		"auto_rotate_period":     defaultTransitKeyConfig.autoRotatePeriod,
	}); err != nil {
		return fmt.Errorf("openbao: create transit/keys/%s: %w", kid, err)
	}
	return nil
}

// destroyTransitKey deletes the per-Deployment transit key. OpenBao
// rejects DELETE on a transit key unless `deletion_allowed=true` is
// first written to its config — we set the flag and then delete, in
// that order. The two-step is intentional: Vault/OpenBao's design
// makes accidental key deletion impossible without an explicit
// affirmative step, and we want to mirror that posture rather than
// shortcut it with a flag at key-create time.
//
// CALLER OBLIGATION: this is irreversible. The adapter's Remove
// requires ConfirmDestroyKey=true before reaching here.
func destroyTransitKey(ctx context.Context, client *bao.Client, kid string) error {
	if kid == "" {
		return fmt.Errorf("%w: kid empty", ErrInvalidInput)
	}

	// Step 1: enable deletion. Write to transit/keys/<kid>/config
	// rather than the key itself; OpenBao's config endpoint accepts
	// the flag without disturbing the key material.
	if _, err := client.Logical().WriteWithContext(ctx, "transit/keys/"+kid+"/config", map[string]any{
		"deletion_allowed": true,
	}); err != nil {
		return fmt.Errorf("openbao: allow deletion on transit/keys/%s: %w", kid, err)
	}

	// Step 2: delete. Best-effort idempotent: a 404-style empty
	// response on a missing key is treated as success.
	if _, err := client.Logical().DeleteWithContext(ctx, "transit/keys/"+kid); err != nil {
		return fmt.Errorf("openbao: delete transit/keys/%s: %w", kid, err)
	}
	return nil
}
