package openbao

import (
	"context"
	"errors"
	"fmt"

	bao "github.com/openbao/openbao/api/v2"
)

// k8sRoleTTL is the lifetime of a token issued by the kubernetes auth
// backend for the per-Deployment role. 1 h is short enough that a leaked
// SA token has a bounded blast radius; the lifetime watcher renews it
// on a 2/3-TTL cadence.
const k8sRoleTTL = "1h"

// k8sRoleMaxTTL is the absolute lifetime ceiling regardless of
// renewals. After 24 h the dataplane pod must re-authenticate from its
// SA JWT, which forces it to re-prove its k8s identity periodically.
const k8sRoleMaxTTL = "24h"

// k8sRoleConfig is the closed set of fields the adapter writes to the
// kubernetes auth role. Kept private so callers can't widen the bound
// service account namespaces or strip the token TTLs without going
// through the package's blessed surface.
type k8sRoleConfig struct {
	BoundServiceAccountNames      []string
	BoundServiceAccountNamespaces []string
	Policies                      []string
	TTL                           string
	MaxTTL                        string
}

// configureK8sRole writes the per-Deployment role at
// auth/kubernetes/role/<roleName>. The role binds the supplied k3s
// ServiceAccount in the supplied namespace to the per-Deployment policy
// with a 1 h / 24 h TTL. Idempotent: re-running with the same config
// is a no-op at the catalog level; re-running with a CHANGED config
// (e.g. a different namespace) overwrites the previous binding, which
// is the desired behaviour for the destroy + re-provision flow.
//
// Returns ErrK8sAuthMissing wrapped from the underlying bao error when
// the kubernetes auth mount is not enabled — that's Phase 4's job and
// surfacing it here gives the operator a runbook hint rather than the
// raw "no handler for path" string from OpenBao.
func configureK8sRole(ctx context.Context, client *bao.Client, roleName string, cfg k8sRoleConfig) error {
	if roleName == "" {
		return fmt.Errorf("%w: role name empty", ErrInvalidInput)
	}
	if len(cfg.BoundServiceAccountNames) == 0 {
		return fmt.Errorf("%w: bound_service_account_names empty", ErrInvalidInput)
	}
	if len(cfg.BoundServiceAccountNamespaces) == 0 {
		return fmt.Errorf("%w: bound_service_account_namespaces empty", ErrInvalidInput)
	}
	if len(cfg.Policies) == 0 {
		return fmt.Errorf("%w: policies empty", ErrInvalidInput)
	}
	if cfg.TTL == "" {
		cfg.TTL = k8sRoleTTL
	}
	if cfg.MaxTTL == "" {
		cfg.MaxTTL = k8sRoleMaxTTL
	}

	body := map[string]any{
		"bound_service_account_names":      cfg.BoundServiceAccountNames,
		"bound_service_account_namespaces": cfg.BoundServiceAccountNamespaces,
		"token_policies":                   cfg.Policies,
		"token_ttl":                        cfg.TTL,
		"token_max_ttl":                    cfg.MaxTTL,
		// We do NOT want the role's tokens to inherit the default
		// policy (which is OpenBao's universal "you can list your own
		// token info" grant). The dataplane pod's token must carry the
		// per-Deployment policy and nothing else — that's the §18.1
		// layer-5 invariant translated to OpenBao terms.
		"token_no_default_policy": true,
		"token_type":              "service",
	}

	if _, err := client.Logical().WriteWithContext(ctx,
		"auth/kubernetes/role/"+roleName, body); err != nil {
		// Distinguish the "auth method not enabled" case from generic
		// errors so the operator knows whether the fix is `make
		// openbao-init` (re-enable the mount) or something else.
		if isAuthMethodNotEnabled(err) {
			return fmt.Errorf("%w: %w", ErrK8sAuthMissing, err)
		}
		return fmt.Errorf("openbao: write auth/kubernetes/role/%s: %w", roleName, err)
	}
	return nil
}

// removeK8sRole deletes the per-Deployment kubernetes auth role.
// Idempotent: OpenBao returns success when the role is absent.
func removeK8sRole(ctx context.Context, client *bao.Client, roleName string) error {
	if roleName == "" {
		return fmt.Errorf("%w: role name empty", ErrInvalidInput)
	}
	if _, err := client.Logical().DeleteWithContext(ctx,
		"auth/kubernetes/role/"+roleName); err != nil {
		return fmt.Errorf("openbao: delete auth/kubernetes/role/%s: %w", roleName, err)
	}
	return nil
}

// readK8sRole is the verification helper. Returns the role's data map
// (or nil when the role is missing) plus any transport error.
func readK8sRole(ctx context.Context, client *bao.Client, roleName string) (map[string]any, error) {
	if roleName == "" {
		return nil, fmt.Errorf("%w: role name empty", ErrInvalidInput)
	}
	sec, err := client.Logical().ReadWithContext(ctx,
		"auth/kubernetes/role/"+roleName)
	if err != nil {
		return nil, fmt.Errorf("openbao: read auth/kubernetes/role/%s: %w", roleName, err)
	}
	if sec == nil || sec.Data == nil {
		return nil, nil
	}
	return sec.Data, nil
}

// isAuthMethodNotEnabled inspects a bao error for the surface OpenBao
// uses to signal a missing auth backend. The 404-style payload comes
// back as a response error whose message contains "no handler for
// route" — we match on that substring because bao/api v2 does not
// expose a typed error for this case.
func isAuthMethodNotEnabled(err error) bool {
	if err == nil {
		return false
	}
	var rerr *bao.ResponseError
	if errors.As(err, &rerr) {
		for _, msg := range rerr.Errors {
			if contains(msg, "no handler for route") || contains(msg, "auth method not enabled") {
				return true
			}
		}
	}
	return contains(err.Error(), "no handler for route")
}

// contains is a tiny strings.Contains wrapper. Kept here so the file
// doesn't depend on strings just for one call.
func contains(s, sub string) bool {
	if len(sub) == 0 {
		return true
	}
	if len(s) < len(sub) {
		return false
	}
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
