// Package k3s implements the k3s-side of the deployments.Provisioner
// contract: render the per-Deployment kustomize overlay, server-side
// apply the resulting manifest set to the cluster with field manager
// `saas-controlplane`, and wait for the data-plane Deployment to roll
// out. Phase 12b ships this adapter behind the `saasctl debug k3s`
// subcommand so the operator can verify CHECKPOINT 6 (cross-namespace
// NetworkPolicy enforcement) before Phase 12e composes it into the full
// 13-step provisioning sequence (AGENTS.md §6.2).
//
// The adapter is intentionally narrow:
//   - Apply  → render + decode + ordered SSA + WaitReady
//   - Remove → Namespace delete (cascades to everything inside)
//   - WaitReady → poll the data-plane Deployment until rollout completes
//
// It does NOT speak to Postgres, OpenBao, or nginx; those land in
// Phase 12c, 12d, 12e respectively.
package k3s

import (
	"context"
	"fmt"
	"strings"
)

// FieldManager is the Kubernetes server-side-apply field manager string
// every Apply uses. Per AGENTS.md §6.5, the control plane owns these
// fields unconditionally, hence Force=true on every ApplyOptions.
// Sharing the manager across all resource kinds is intentional: the
// adapter is the sole writer for resources it creates.
const FieldManager = "saas-controlplane"

// Adapter is the contract the composite provisioner (Phase 12e) calls.
// Kept narrow on purpose — the three lifecycle verbs the k3s layer
// needs, nothing more. The interface is here (not in `internal/
// controlplane/deployments`) so other packages can fake-implement it
// for unit tests without importing the heavy client-go shim.
type Adapter interface {
	// Apply renders the per-Deployment overlay, decodes the multi-doc
	// YAML, and server-side-applies each object in
	// Namespace → ServiceAccount → NetworkPolicy → Service → Deployment
	// order. After the last Apply, blocks on WaitReady. Idempotent and
	// safe to retry.
	Apply(ctx context.Context, in ApplyInput) error

	// Remove deletes the Deployment's namespace. K8s garbage-collects
	// every namespaced resource inside (pods, services, network
	// policies, service accounts). Cluster-scoped artifacts (none for
	// us in Phase 12b) are NOT touched.
	Remove(ctx context.Context, in RemoveInput) error

	// WaitReady polls the data-plane Deployment in the namespace until
	// the rollout is complete or the context deadline expires. Used
	// internally by Apply but exported so the operator (via saasctl
	// debug) can wait on an already-applied deployment.
	WaitReady(ctx context.Context, deploymentID string) error
}

// ApplyInput is the data the adapter needs to render + apply one
// per-Deployment manifest set. The caller (Phase 12e) constructs this
// from the deployment row + the operator-supplied host network config;
// the adapter does NOT read the control-plane DB.
//
// All three host CIDRs are REQUIRED. A missing CIDR combined with
// default-deny would trap pods (no DNS = crash, no Postgres = crash);
// the defense-in-depth check in Validate refuses to render a manifest
// set with an empty CIDR.
type ApplyInput struct {
	// DeploymentID is the `dep_<ulid>` identifier. Used as the
	// namespace suffix, the SAAS_DEPLOYMENT_ID env var, and the
	// resource label. Must satisfy isSafeDeploymentID.
	DeploymentID string

	// ProjectSlug + EnvironmentSlug feed the resource labels (commonLabels
	// in the overlay). Phase 12b CP-6 uses DeploymentID for both when
	// the operator does not supply explicit values; Phase 12e wires the
	// real project + environment from the deployments service.
	ProjectSlug     string
	EnvironmentSlug string

	// ImageVersion is the data-plane image tag the overlay's images:
	// block substitutes into the base Deployment. Required; the adapter
	// refuses an empty value so we never accidentally roll out
	// `:placeholder`.
	ImageVersion string

	// NodePort is the unique-per-deployment NodePort the host nginx
	// upstream targets. Must fall in the k3s NodePort range
	// 30000-32767 (the adapter enforces this even though kustomize +
	// the API server would also reject out-of-range values).
	NodePort int

	// HostNginxCIDR is the source CIDR for the
	// allow-ingress-from-host-nginx NetworkPolicy. Typically the k3s
	// node-host CIDR or /32 of the host nginx IP.
	HostNginxCIDR string

	// HostPostgresCIDR is the destination CIDR for the egress allow
	// rule that lets the data-plane reach the per-Deployment Postgres
	// DB on the host (tcp/5432).
	HostPostgresCIDR string

	// HostOpenBaoCIDR is the destination CIDR for the egress allow
	// rule that lets the data-plane reach the host OpenBao for transit
	// wrap/unwrap (tcp/8200). In the base manifest both Postgres and
	// OpenBao share a single ipBlock + dual-port rule, so the renderer
	// uses HostPostgresCIDR for the actual patch — HostOpenBaoCIDR is
	// validated here so that when AGENTS.md §6 splits the rule (the
	// proper L4 isolation hardening, deferred to v1), the caller is
	// already supplying the value.
	HostOpenBaoCIDR string
}

// Validate enforces the Phase 12b input contract. Run inside Apply
// before any kustomize work — fast, no I/O.
func (in ApplyInput) Validate() error {
	if in.DeploymentID == "" {
		return fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}
	if !isSafeDeploymentID(in.DeploymentID) {
		return fmt.Errorf("%w: deployment_id %q has unsafe characters", ErrInvalidInput, in.DeploymentID)
	}
	if in.ImageVersion == "" {
		return fmt.Errorf("%w: image_version empty", ErrInvalidInput)
	}
	if strings.ContainsAny(in.ImageVersion, " \t\n\r\"';") {
		return fmt.Errorf("%w: image_version has unsafe characters", ErrInvalidInput)
	}
	if in.NodePort < 30000 || in.NodePort > 32767 {
		return fmt.Errorf("%w: node_port %d out of k3s nodeport range 30000-32767", ErrInvalidInput, in.NodePort)
	}
	if in.HostNginxCIDR == "" {
		return fmt.Errorf("%w: host_nginx_cidr empty (default-deny + missing allow traps pods)", ErrMissingCIDR)
	}
	if in.HostPostgresCIDR == "" {
		return fmt.Errorf("%w: host_postgres_cidr empty (default-deny + missing allow traps pods)", ErrMissingCIDR)
	}
	if in.HostOpenBaoCIDR == "" {
		return fmt.Errorf("%w: host_openbao_cidr empty (default-deny + missing allow traps pods)", ErrMissingCIDR)
	}
	for _, p := range []struct{ field, val string }{
		{"host_nginx_cidr", in.HostNginxCIDR},
		{"host_postgres_cidr", in.HostPostgresCIDR},
		{"host_openbao_cidr", in.HostOpenBaoCIDR},
	} {
		if strings.ContainsAny(p.val, " \t\n\r\"';") {
			return fmt.Errorf("%w: %s has unsafe characters", ErrInvalidInput, p.field)
		}
	}
	return nil
}

// NamespaceName returns the cluster namespace the adapter materialises
// for a Deployment. The adapter and CLI use this in error messages and
// when calling Get/Delete by name.
func (in ApplyInput) NamespaceName() string {
	return NamespacePrefix + in.DeploymentID
}

// RemoveInput is the destroy contract. We separate it from ApplyInput
// so the caller is forced to think about which side they are on.
type RemoveInput struct {
	DeploymentID string
}

// Validate enforces the destroy input contract — same alphabet rules
// as ApplyInput.DeploymentID.
func (in RemoveInput) Validate() error {
	if in.DeploymentID == "" {
		return fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}
	if !isSafeDeploymentID(in.DeploymentID) {
		return fmt.Errorf("%w: deployment_id %q has unsafe characters", ErrInvalidInput, in.DeploymentID)
	}
	return nil
}

// NamespaceName mirrors ApplyInput.NamespaceName.
func (in RemoveInput) NamespaceName() string {
	return NamespacePrefix + in.DeploymentID
}

// NamespacePrefix is the cluster-namespace prefix every Deployment's
// resources live under. Kept as a constant rather than a config knob
// because RBAC + audit rely on the predictable shape `saas-<dep_id>`.
const NamespacePrefix = "saas-"

// DataPlaneDeploymentName is the apps/v1 Deployment name inside every
// per-Deployment namespace. Hard-coded because the base manifest sets
// it; making it configurable would mean the operator could roll out
// two data planes side-by-side which violates the per-namespace
// isolation invariant.
const DataPlaneDeploymentName = "dataplane"

// isSafeDeploymentID restricts deployment IDs to the alphabet the
// platform already enforces (Crockford-ish ULID + `dep_` prefix). We
// embed this value in resource names; an unsafe character could create
// a name that the API server rejects (or worse, accepts under a
// different identity).
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
