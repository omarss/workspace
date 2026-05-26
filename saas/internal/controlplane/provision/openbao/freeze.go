package openbao

import (
	"context"
	"encoding/json"
	"fmt"
)

// FreezeKeys disables the per-Deployment transit key by raising its
// min_decryption_version above the current key version. After Freeze,
// any decrypt request fails with `key version not in min_decryption
// range`; encrypt requests are blocked by the matching
// min_encryption_version. The platform's PII reads stop working
// immediately; PII writes also stop because new encrypts fail. This
// is the incident-response "lock down everything" handle.
//
// §18.7. Reversible by an operator with step-up auth (Phase 13);
// until then, thaw is the manual `bao write
// transit/keys/<id>/config min_decryption_version=1
// min_encryption_version=1`.
//
// The implementation reads the current latest_version, then writes
// min_decryption_version = min_encryption_version = latest_version + 1
// so even the current version is unusable. This is the cleanest
// "lock now" posture without destroying the key material (destroy is
// what Remove does; Freeze is the reversible lock).
func (a *HostAdapter) FreezeKeys(ctx context.Context, deploymentID string) error {
	if deploymentID == "" {
		return fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}
	if !isSafeDeploymentID(deploymentID) {
		return fmt.Errorf("%w: deployment_id %q has unsafe characters", ErrInvalidInput, deploymentID)
	}

	keyPath := "transit/keys/" + deploymentID
	sec, err := a.client.Logical().ReadWithContext(ctx, keyPath)
	if err != nil {
		return fmt.Errorf("openbao: read %s: %w", keyPath, err)
	}
	if sec == nil || sec.Data == nil {
		return fmt.Errorf("%w: %s missing", ErrVerificationFailed, keyPath)
	}
	latest := decodeLatestVersion(sec.Data)
	if _, err := a.client.Logical().WriteWithContext(ctx,
		keyPath+"/config",
		map[string]any{
			"min_decryption_version": latest + 1,
			"min_encryption_version": latest + 1,
		}); err != nil {
		return fmt.Errorf("openbao: freeze %s: %w", keyPath, err)
	}
	return nil
}

// decodeLatestVersion reads the `latest_version` field from a
// transit/keys/<id> response. Defaults to 1 when the field is missing
// or has an unexpected type — every per-Deployment key has at least
// one version (created at provision time), so a missing field is a
// defensive fallback.
func decodeLatestVersion(data map[string]any) int {
	raw, ok := data["latest_version"]
	if !ok {
		return 1
	}
	switch v := raw.(type) {
	case int:
		return v
	case int64:
		return int(v)
	case float64:
		return int(v)
	case json.Number:
		if n, err := v.Int64(); err == nil {
			return int(n)
		}
	}
	return 1
}
