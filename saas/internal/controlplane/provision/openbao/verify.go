package openbao

import (
	"context"
	"fmt"
	"strings"

	bao "github.com/openbao/openbao/api/v2"
)

// verifyAccess confirms all four core artifacts are present on the
// cluster for the given deployment_id:
//
//  1. transit key at transit/keys/<dep_id>
//  2. policy at sys/policies/acl/saas-<dep_id>
//  3. kubernetes auth role at auth/kubernetes/role/<dep_id>
//  4. KV marker at secret/data/<dep_id>/_provisioned
//  5. at least one audit device is enabled (Phase 4 invariant)
//
// Each missing artifact returns an ErrVerificationFailed wrapped with
// the offending name so the operator's runbook can target the fix.
// VerifyAccess does NOT modify state — it is a read-only probe.
func verifyAccess(ctx context.Context, client *bao.Client, deploymentID string) error {
	if deploymentID == "" {
		return fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}

	// 1. Transit key.
	sec, err := client.Logical().ReadWithContext(ctx, "transit/keys/"+deploymentID)
	if err != nil {
		return fmt.Errorf("%w: read transit/keys/%s: %w", ErrVerificationFailed, deploymentID, err)
	}
	if sec == nil || sec.Data == nil {
		return fmt.Errorf("%w: transit/keys/%s missing", ErrVerificationFailed, deploymentID)
	}

	// 2. Policy.
	policyName := "saas-" + deploymentID
	got, err := readPolicy(ctx, client, policyName)
	if err != nil {
		return fmt.Errorf("%w: read policy %s: %w", ErrVerificationFailed, policyName, err)
	}
	if got == "" {
		return fmt.Errorf("%w: policy %s missing", ErrVerificationFailed, policyName)
	}
	// Verify the policy mentions the deployment_id in the expected
	// shape — a hand-edit that widened the policy to a glob would
	// breach the §18.1 layer-5 invariant. We don't compare the full
	// rendered template (whitespace, comments, ordering may drift) but
	// we do require the deployment_id to be the literal substituted
	// into every path line.
	if !strings.Contains(got, deploymentID) {
		return fmt.Errorf("%w: policy %s does not reference deployment_id", ErrVerificationFailed, policyName)
	}

	// 3. Kubernetes auth role.
	roleData, err := readK8sRole(ctx, client, deploymentID)
	if err != nil {
		return fmt.Errorf("%w: read auth/kubernetes/role/%s: %w", ErrVerificationFailed, deploymentID, err)
	}
	if roleData == nil {
		return fmt.Errorf("%w: auth/kubernetes/role/%s missing", ErrVerificationFailed, deploymentID)
	}
	// Confirm the role's policies list includes the per-Deployment
	// policy — a role pointing at the wrong policy would silently let
	// the pod authenticate but with zero useful grants.
	if !rolePoliciesIncludes(roleData, policyName) {
		return fmt.Errorf("%w: auth/kubernetes/role/%s does not bind policy %s",
			ErrVerificationFailed, deploymentID, policyName)
	}

	// 4. KV marker.
	marker, err := readKVMarker(ctx, client, deploymentID)
	if err != nil {
		return fmt.Errorf("%w: read kv marker: %w", ErrVerificationFailed, err)
	}
	if marker == nil {
		return fmt.Errorf("%w: kv marker at secret/data/%s/%s missing",
			ErrVerificationFailed, deploymentID, provisionedMarkerPath)
	}

	// 5. At least one audit device. Phase 4 bootstrap installs the
	// shared file device; per-Deployment policy events ride on it.
	if err := verifyAuditEnabled(ctx, client); err != nil {
		return err
	}

	return nil
}

// rolePoliciesIncludes inspects the kubernetes auth role's token_policies
// (preferred name) or policies (legacy) field for the target policy
// name. OpenBao's API returns the field as []any of strings, so we
// flatten with a defensive type assertion.
func rolePoliciesIncludes(roleData map[string]any, target string) bool {
	for _, key := range []string{"token_policies", "policies"} {
		raw, ok := roleData[key]
		if !ok || raw == nil {
			continue
		}
		switch v := raw.(type) {
		case []any:
			for _, p := range v {
				if s, ok := p.(string); ok && s == target {
					return true
				}
			}
		case []string:
			for _, s := range v {
				if s == target {
					return true
				}
			}
		}
	}
	return false
}
