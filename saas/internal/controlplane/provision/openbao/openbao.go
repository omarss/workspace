// Package openbao is the control-plane's per-Deployment OpenBao adapter.
// For each Deployment it ensures the transit key, writes the per-Deployment
// HCL policy (rendered from the embedded template), configures the
// Kubernetes auth role bound to the Phase 12b dataplane ServiceAccount,
// and seeds the KV v2 path namespace.
//
// Phase 12d ships the adapter in isolation — it is NOT wired into the
// LocalProvisioner from Phase 11. Phase 12e composes the full §6.2
// 13-step provisioning sequence with this adapter alongside the k3s,
// nginx, and Postgres adapters. The only callers in Phase 12d are:
//
//   - The integration tests in this package (testcontainers-backed
//     OpenBao or a running compose dev instance).
//   - The `saasctl debug bao apply <dep_id>` CP-8 verification command
//     (build-tagged `!prod`).
//
// Audit device strategy: this adapter does NOT enable a per-Deployment
// file audit device. Audit lives on the single shared file declared in
// `deploy/openbao/config/openbao.hcl` (enabled at Phase 4 bootstrap);
// every operation issued under a per-Deployment policy is tagged with
// the policy name on the audit line, so per-Deployment forensics
// remains possible via grep / structured ingestion. The trade-off is
// documented in ADR 016. OpenBao's hard limit on audit devices makes
// per-Deployment files non-viable at 100s of Deployments scale.
//
// See docs/plans/mvp/13d-openbao-provisioner.md, AGENTS.md §18.7, and
// docs/plans/mvp/01-foundations.md §5 for the operator-facing contract.
package openbao

import (
	"context"
	"fmt"
)

// Adapter is the contract the composite provisioner (Phase 12e) calls.
// Kept narrow on purpose — provision, remove, verify. The interface
// lives here so other packages can fake-implement it without pulling in
// the OpenBao HTTP client.
type Adapter interface {
	// Apply provisions the per-Deployment OpenBao state:
	//   1. EnsureTransitKey: write transit/keys/<dep_id> if missing.
	//   2. WritePolicy: render the embedded template with dep_id and
	//      install via sys/policies/acl/saas-<dep_id>.
	//   3. ConfigureK8sRole: bind the per-Deployment SA in saas-<dep_id>
	//      namespace to the saas-<dep_id> policy via auth/kubernetes/
	//      role/<dep_id> (ttl=1h, max_ttl=24h).
	//   4. InitKVPath: create an empty provisioned marker so the
	//      secret/data/<dep_id>/ namespace is visible to operators.
	//   5. VerifyAccess: read each piece back to confirm the apply
	//      landed (catches partial failures that the underlying writes
	//      may swallow on retry).
	//
	// Apply is idempotent: re-running on an already-provisioned
	// Deployment is a no-op at the OpenBao layer because every step
	// either reads-before-write or is a write-with-same-content. Any
	// step's failure surfaces a wrapped sentinel from errors.go so the
	// caller can distinguish "transit key conflict" from "policy
	// conflict" without parsing strings.
	Apply(ctx context.Context, in ApplyInput) (ApplyResult, error)

	// Remove deletes the per-Deployment OpenBao artifacts. Requires
	// RemoveInput.ConfirmDestroyKey=true; deleting a transit key is
	// IRREVERSIBLE — any ciphertext encrypted under that key becomes
	// permanently undecryptable. The adapter refuses to execute the
	// delete chain without explicit confirmation.
	//
	// Order: KV path marker, k8s role, policy, transit key. The transit
	// key delete needs `deletion_allowed=true` on the key config first;
	// the adapter sets the flag immediately before the delete.
	Remove(ctx context.Context, in RemoveInput) error

	// VerifyAccess confirms the four core artifacts are present on
	// OpenBao for the given deployment_id: transit key, policy, k8s
	// role, KV path marker. Exposed separately from Apply so the
	// operator (via `saasctl debug bao verify`) can re-check state on
	// an existing deployment without rewriting any state.
	VerifyAccess(ctx context.Context, deploymentID string) error
}

// ApplyInput is the data Apply needs. Caller (Phase 12e or saasctl debug)
// supplies the deployment_id, the k3s namespace + ServiceAccount the SA
// is in, and an optional audit log path the operator may use to seed a
// dedicated audit device (deferred per ADR 016 — see package doc).
type ApplyInput struct {
	// DeploymentID is the `dep_<ulid>` identifier. Used verbatim as the
	// transit key id (kid), the auth/kubernetes/role/ name, and the KV
	// namespace prefix; per the §18.1 layer-5 invariant `kid ==
	// deployment_id` for every per-Deployment key.
	DeploymentID string

	// K3sNamespace is the per-Deployment namespace Phase 12b creates,
	// canonically `saas-<dep_id>`. Bound on the kubernetes auth role as
	// the only namespace whose SA may exchange a token under the
	// per-Deployment policy.
	K3sNamespace string

	// K3sServiceAccount is the SA name Phase 12b's PR #19 fix added to
	// every per-Deployment namespace, canonically `dataplane`. Bound on
	// the kubernetes auth role as the only SA name whose JWT may
	// exchange a token under the per-Deployment policy. Specifying
	// "default" would let any pod in the namespace authenticate as the
	// Deployment — anti-pattern.
	K3sServiceAccount string

	// AuditLogPath is informational for Phase 12d. ADR 016 records that
	// the per-Deployment audit device is deferred in favour of the
	// single shared file from Phase 4 bootstrap; this field is reserved
	// so the future per-device path can be supplied without an
	// ApplyInput signature change.
	AuditLogPath string
}

// Validate enforces the Phase 12d input contract.
//
// Slug validation is strict because the deployment_id is concatenated
// into OpenBao API paths (transit/keys/<id>, sys/policies/acl/saas-<id>,
// auth/kubernetes/role/<id>, secret/data/<id>/...). Anything outside the
// known safe alphabet would either path-traverse into another
// Deployment's namespace or break OpenBao's identifier rules.
func (in ApplyInput) Validate() error {
	if in.DeploymentID == "" {
		return fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}
	if !isSafeDeploymentID(in.DeploymentID) {
		return fmt.Errorf("%w: deployment_id %q has unsafe characters", ErrInvalidInput, in.DeploymentID)
	}
	if in.K3sNamespace == "" {
		return fmt.Errorf("%w: k3s_namespace empty", ErrInvalidInput)
	}
	if !isSafeK8sName(in.K3sNamespace) {
		return fmt.Errorf("%w: k3s_namespace %q has unsafe characters", ErrInvalidInput, in.K3sNamespace)
	}
	if in.K3sServiceAccount == "" {
		return fmt.Errorf("%w: k3s_service_account empty", ErrInvalidInput)
	}
	if !isSafeK8sName(in.K3sServiceAccount) {
		return fmt.Errorf("%w: k3s_service_account %q has unsafe characters", ErrInvalidInput, in.K3sServiceAccount)
	}
	return nil
}

// PolicyName returns the canonical policy name `saas-<dep_id>`. Stable
// across calls; the `saas-` prefix prevents collisions with operator
// policies installed manually (e.g. `controlplane-manage`).
func (in ApplyInput) PolicyName() string {
	return "saas-" + in.DeploymentID
}

// K8sRoleName returns the canonical kubernetes auth role name. The
// envelope.Client in Phase 4 wires `role = deployment_id` directly —
// keep this in sync.
func (in ApplyInput) K8sRoleName() string {
	return in.DeploymentID
}

// KVPath returns the KV v2 data path prefix the policy scopes to.
// `secret/data/<dep_id>/` plus any tail the caller writes is allowed by
// the policy; siblings under a different `<dep_id>` are not.
func (in ApplyInput) KVPath() string {
	return "secret/data/" + in.DeploymentID
}

// ApplyResult is what Apply returns on success. Fields mirror the
// OpenBao paths Phase 12e will reference when composing the full §6.2
// 13-step provisioning sequence.
type ApplyResult struct {
	// Kid is the transit key id (= deployment_id). Returned so the
	// caller does not have to recompute the §18.1 layer-5 invariant.
	Kid string

	// PolicyName is `saas-<dep_id>`. The audit subscriber (Phase 10)
	// uses this string to route shared-audit-file entries into the
	// correct per-Deployment audit_event partition.
	PolicyName string

	// K8sRoleName is `<dep_id>`. Phase 12b's dataplane Deployment must
	// set `role = <dep_id>` when constructing its envelope.Client; the
	// equality is asserted at boot-time so a typo crash-loops the pod
	// rather than silently failing open.
	K8sRoleName string

	// KVPath is `secret/data/<dep_id>`. Children scoped by the policy
	// include the Phase 12c-stored Postgres app password, future HMAC
	// keys, and customer-managed secrets per ADR 017.
	KVPath string
}

// RemoveInput is what Remove takes. The ConfirmDestroyKey flag is
// REQUIRED because deleting a transit key is IRREVERSIBLE — any
// ciphertext encrypted under that key becomes permanently undecryptable
// after Remove returns.
type RemoveInput struct {
	DeploymentID string

	// ConfirmDestroyKey MUST be true for Remove to execute. The
	// adapter returns ErrConfirmationRequired otherwise. Defense in
	// depth against accidental cluster-wide destruction (saasctl debug
	// also gates this behind a CLI flag with a 5-second countdown).
	ConfirmDestroyKey bool
}

// Validate enforces the destroy contract.
func (in RemoveInput) Validate() error {
	if in.DeploymentID == "" {
		return fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}
	if !isSafeDeploymentID(in.DeploymentID) {
		return fmt.Errorf("%w: deployment_id %q has unsafe characters", ErrInvalidInput, in.DeploymentID)
	}
	if !in.ConfirmDestroyKey {
		return ErrConfirmationRequired
	}
	return nil
}

// PolicyName mirrors ApplyInput.PolicyName for Remove parity.
func (in RemoveInput) PolicyName() string {
	return "saas-" + in.DeploymentID
}

// K8sRoleName mirrors ApplyInput.K8sRoleName for Remove parity.
func (in RemoveInput) K8sRoleName() string {
	return in.DeploymentID
}

// isSafeDeploymentID restricts deployment IDs to the same ULID-ish
// alphabet the other adapters accept. The value lands in OpenBao API
// paths so refuse anything that could path-traverse (`/`, `..`, etc.)
// or collide with reserved characters in HCL.
func isSafeDeploymentID(s string) bool {
	if s == "" || len(s) > 64 {
		return false
	}
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z':
		case r >= 'A' && r <= 'Z':
		case r >= '0' && r <= '9':
		case r == '_' || r == '-':
		default:
			return false
		}
	}
	return true
}

// isSafeK8sName mirrors the Kubernetes name validation surface (RFC 1123
// labels): lowercase alphanumerics and hyphens, 1–63 chars, no leading
// or trailing hyphen. We allow it slightly stricter than k8s here —
// k8s permits dots in some name kinds but our use cases (namespace +
// ServiceAccount) do not, so a flat alphabet is safer.
func isSafeK8sName(s string) bool {
	if s == "" || len(s) > 63 {
		return false
	}
	if s[0] == '-' || s[len(s)-1] == '-' {
		return false
	}
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z':
		case r >= '0' && r <= '9':
		case r == '-':
		default:
			return false
		}
	}
	return true
}
