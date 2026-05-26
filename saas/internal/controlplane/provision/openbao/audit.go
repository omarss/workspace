package openbao

import (
	"context"
	"fmt"

	bao "github.com/openbao/openbao/api/v2"
)

// Per-Deployment audit device choice (ADR 016): the adapter does NOT
// enable a dedicated file audit device per Deployment because OpenBao
// has a small fixed limit on audit devices (~10) and 100s of
// Deployments would blow through it. The single shared file declared
// in deploy/openbao/config/openbao.hcl is enabled at Phase 4 bootstrap
// and every operation under the per-Deployment policy is automatically
// tagged with the policy name on the audit line — that's the routing
// key the Phase 10 audit subscriber uses to land entries into the
// correct per-Deployment audit_event table.
//
// The helpers below are reserved for the future per-Deployment audit
// device path (e.g. when an operator opts in for a single highly
// regulated Deployment). They are NOT called from Apply / Remove in
// Phase 12d.

// AuditDevicePath returns the canonical per-Deployment audit device
// path (`file-<dep_id>`). Exported so the future opt-in code path
// (e.g. a single compliance-sensitive Deployment that needs its own
// audit stream) can reference the canonical name without duplicating
// the format string. Phase 12d does not call this — the shared audit
// device is sufficient per ADR 016. Kept exported rather than
// unexported-but-unused so the linter does not strip it and a future
// implementer has a clear extension point.
func AuditDevicePath(deploymentID string) string {
	return "file-" + deploymentID
}

// verifyAuditEnabled confirms at least one audit device is enabled on
// the cluster. If none is enabled the per-Deployment access events
// will not be recorded — and AGENTS.md §18.7's "every key access
// logged" invariant fails. The adapter verifies this in VerifyAccess
// rather than enabling an audit device itself; the Phase 4 bootstrap
// owns audit device creation.
func verifyAuditEnabled(ctx context.Context, client *bao.Client) error {
	sec, err := client.Logical().ReadWithContext(ctx, "sys/audit")
	if err != nil {
		return fmt.Errorf("openbao: list audit devices: %w", err)
	}
	if sec == nil || sec.Data == nil {
		return fmt.Errorf("%w: no audit devices enabled (expected at least one from Phase 4 bootstrap)",
			ErrVerificationFailed)
	}
	if len(sec.Data) == 0 {
		return fmt.Errorf("%w: no audit devices enabled (expected at least one from Phase 4 bootstrap)",
			ErrVerificationFailed)
	}
	return nil
}
