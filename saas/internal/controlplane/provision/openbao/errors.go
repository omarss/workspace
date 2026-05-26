package openbao

import "errors"

// Sentinel errors. Callers compare with errors.Is — Validate / Apply /
// VerifyAccess / Remove always wrap with %w so the chain stays intact
// for the Phase 12e deployment_provision_step status mapping.
var (
	// ErrInvalidInput signals a caller-side bug: an unsafe deployment_id,
	// empty k3s namespace, etc. Treat as permanent — never retried by
	// the destroy reconciler.
	ErrInvalidInput = errors.New("openbao: invalid input")

	// ErrKidExists is reserved for the explicit "I expected to create a
	// fresh transit key and one already exists" caller scenario. Apply
	// itself is idempotent and does NOT return this — it is returned by
	// the lower-level EnsureTransitKey helper when invoked outside the
	// Apply flow (e.g. a future force-recreate path).
	ErrKidExists = errors.New("openbao: transit key already exists")

	// ErrPolicyConflict surfaces when the rendered policy content
	// disagrees with the on-disk policy at the same name. Apply writes
	// the same content for the same deployment_id so this only fires
	// when an operator hand-edited the policy or when the template
	// changed without a coordinated re-apply. Caller's remediation:
	// inspect both versions, decide which is correct, force-overwrite.
	ErrPolicyConflict = errors.New("openbao: per-deployment policy disagrees with rendered template")

	// ErrK8sAuthMissing fires when ConfigureK8sRole notices the
	// `auth/kubernetes/` mount is not enabled. The Phase 4 bootstrap
	// enables this auth method exactly once — surfacing this error in
	// production means the OpenBao state was tampered with.
	ErrK8sAuthMissing = errors.New("openbao: auth/kubernetes/ mount is not enabled (run make openbao-init)")

	// ErrAuditDeviceConflict is reserved for the per-Deployment audit
	// device path (deferred per ADR 016). Kept as a sentinel so the
	// future code path can wire in without breaking the public API.
	ErrAuditDeviceConflict = errors.New("openbao: audit device already enabled at a different file path")

	// ErrConfirmationRequired guards the destructive Remove path behind
	// an explicit flag on RemoveInput. Returned without touching the
	// cluster when ConfirmDestroyKey=false.
	ErrConfirmationRequired = errors.New("openbao: destroy transit key requires explicit confirmation")

	// ErrVerificationFailed wraps the inner cause when VerifyAccess
	// finds one of the four artifacts missing. The wrapped error names
	// the offending artifact (transit key / policy / k8s role / KV
	// marker) so the operator's runbook can target the fix.
	ErrVerificationFailed = errors.New("openbao: post-apply verification failed")

	// ErrUnexpectedResponse covers the case where the OpenBao API
	// returns a 2xx but the payload shape doesn't match what we expect
	// (e.g. a `type` field of unexpected value on a transit key read).
	// Distinct from ErrVerificationFailed because the remediation is to
	// inspect bao directly rather than re-apply.
	ErrUnexpectedResponse = errors.New("openbao: unexpected response shape from API")
)
