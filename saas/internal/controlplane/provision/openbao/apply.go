package openbao

import (
	"context"
	"fmt"

	bao "github.com/openbao/openbao/api/v2"
)

// HostAdapter is the production implementation of Adapter. It speaks
// directly to OpenBao via the openbao/api/v2 client. The adapter is
// stateless — every public method takes a *bao.Client supplied at
// construction; callers own its lifecycle so the lifetime watcher
// stays alive across operations.
//
// The constructor takes a pre-authenticated client rather than the raw
// ClientConfig because the host-process auth (AppRole) is owned by the
// composite provisioner in Phase 12e, which needs to share a single
// client across all the per-Deployment provisioning steps (transit
// key, KV writes, etc.) without a fresh login on every call.
type HostAdapter struct {
	client *bao.Client
}

// NewHostAdapter wraps a pre-authenticated *bao.Client. The client
// MUST be configured with a token that has at minimum the following
// capabilities on the platform's OpenBao:
//
//   - sudo on transit/keys/* + transit/keys/<id>/config (create / delete)
//   - sudo on sys/policies/acl/* (write / delete)
//   - sudo on auth/kubernetes/role/* (write / delete)
//   - create/read/update/delete on secret/data/* + secret/metadata/*
//   - read on sys/audit
//
// Phase 4's `controlplane-manage` AppRole policy (created by `make
// openbao-init`) carries this set. In production the AppRole is the
// only sanctioned identity that may invoke the adapter; the dev path
// uses the root token via saasctl debug bao with --bao-token-file
// pointed at /openbao/secrets/init.json.
func NewHostAdapter(client *bao.Client) (*HostAdapter, error) {
	if client == nil {
		return nil, fmt.Errorf("%w: bao client nil", ErrInvalidInput)
	}
	return &HostAdapter{client: client}, nil
}

// Apply runs the five-step provisioning flow described in the package
// doc. Step order is fixed:
//
//  1. EnsureTransitKey — must precede policy because the policy
//     references the transit path; OpenBao does not validate the
//     reference but we want the encrypt/decrypt paths to be live
//     before any pod tries to use them.
//  2. WritePolicy — the policy must exist before the kubernetes role
//     references it; OpenBao rejects a role pointing at a missing
//     policy.
//  3. ConfigureK8sRole — binds the SA to the policy.
//  4. InitKVPath — seeds the namespace marker; the policy permits the
//     write, so it must follow steps 2 and 3 if the adapter ever
//     downgrades to using the per-Deployment policy for its own
//     writes. Today the adapter uses the AppRole token (which has
//     KV-wide grants), so the order here is purely for
//     verification-symmetry.
//  5. VerifyAccess — read each artifact back. Catches partial
//     failures that might have returned 2xx-but-empty from earlier
//     steps.
func (a *HostAdapter) Apply(ctx context.Context, in ApplyInput) (ApplyResult, error) {
	if err := in.Validate(); err != nil {
		return ApplyResult{}, err
	}

	// 1. Transit key.
	if err := ensureTransitKey(ctx, a.client, in.DeploymentID); err != nil {
		return ApplyResult{}, fmt.Errorf("transit key: %w", err)
	}

	// 2. Per-Deployment policy.
	rendered, err := renderPolicy(in.DeploymentID)
	if err != nil {
		return ApplyResult{}, fmt.Errorf("render policy: %w", err)
	}
	policyName := in.PolicyName()
	if err := writePolicy(ctx, a.client, policyName, rendered); err != nil {
		return ApplyResult{}, fmt.Errorf("policy: %w", err)
	}

	// 3. Kubernetes auth role.
	roleName := in.K8sRoleName()
	if err := configureK8sRole(ctx, a.client, roleName, k8sRoleConfig{
		BoundServiceAccountNames:      []string{in.K3sServiceAccount},
		BoundServiceAccountNamespaces: []string{in.K3sNamespace},
		Policies:                      []string{policyName},
		TTL:                           k8sRoleTTL,
		MaxTTL:                        k8sRoleMaxTTL,
	}); err != nil {
		return ApplyResult{}, fmt.Errorf("k8s auth role: %w", err)
	}

	// 4. KV namespace marker.
	if err := initKVPath(ctx, a.client, in.DeploymentID); err != nil {
		return ApplyResult{}, fmt.Errorf("kv namespace: %w", err)
	}

	// 5. Verify the apply landed correctly.
	if err := verifyAccess(ctx, a.client, in.DeploymentID); err != nil {
		return ApplyResult{}, err
	}

	return ApplyResult{
		Kid:         in.DeploymentID,
		PolicyName:  policyName,
		K8sRoleName: roleName,
		KVPath:      in.KVPath(),
	}, nil
}

// Remove deletes the per-Deployment OpenBao artifacts. Order:
//
//  1. KV tree — purge metadata under secret/metadata/<dep_id>/.
//  2. k8s auth role.
//  3. Policy.
//  4. Transit key (after allow-deletion config).
//
// Best-effort idempotent: a missing artifact in any step is treated as
// success. We continue through the chain even if one step's transport
// fails so the operator gets the maximum cleanup possible from a
// single Remove call. The combined error chain is returned at the
// end.
//
// CALLER OBLIGATION: this destroys the transit key. Ciphertext
// encrypted under the destroyed key is permanently unrecoverable.
// RemoveInput.ConfirmDestroyKey gates the call; saasctl debug bao
// remove gates it again behind a 5-second countdown.
func (a *HostAdapter) Remove(ctx context.Context, in RemoveInput) error {
	if err := in.Validate(); err != nil {
		return err
	}

	// Collect errors and return them together so a transport hiccup
	// on one step doesn't blind the operator to others.
	var firstErr error
	record := func(label string, err error) {
		if err == nil {
			return
		}
		if firstErr == nil {
			firstErr = fmt.Errorf("%s: %w", label, err)
		}
	}

	record("kv tree", removeKVPath(ctx, a.client, in.DeploymentID))
	record("k8s auth role", removeK8sRole(ctx, a.client, in.K8sRoleName()))
	record("policy", deletePolicy(ctx, a.client, in.PolicyName()))
	record("transit key", destroyTransitKey(ctx, a.client, in.DeploymentID))

	return firstErr
}

// VerifyAccess re-runs the read-only probe Apply uses internally.
// Useful for the operator to re-check state on an existing Deployment
// (e.g. after a manual `bao policy edit`) without rewriting anything.
func (a *HostAdapter) VerifyAccess(ctx context.Context, deploymentID string) error {
	return verifyAccess(ctx, a.client, deploymentID)
}
