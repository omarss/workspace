package authorization

import (
	"context"
	"sync/atomic"
)

// PermissionChecker is the narrow interface used by sibling modules to
// enforce authorization on destructive operations. Modules MUST NOT
// depend on the full authorization.Service — they take a
// PermissionChecker so the dependency graph stays one-way and the test
// surface narrow (a fake checker is a one-liner).
//
// Empty memberID means the caller is unauthenticated or comes from an
// unauthenticated path — return (false, nil) in that case. Callers
// typically AssertTenant first which would have already 401'd, but
// defence in depth applies.
type PermissionChecker interface {
	HasPermission(ctx context.Context, memberID, tenantID, permission string) (bool, error)
}

// CheckerFunc adapts a plain function to PermissionChecker. Tests
// usually supply a CheckerFunc that returns a hard-coded answer.
type CheckerFunc func(ctx context.Context, memberID, tenantID, permission string) (bool, error)

// HasPermission implements PermissionChecker.
func (f CheckerFunc) HasPermission(ctx context.Context, memberID, tenantID, permission string) (bool, error) {
	return f(ctx, memberID, tenantID, permission)
}

// HasPermission lets the authorization.Service satisfy PermissionChecker
// without exposing its full surface to siblings. The implementation
// reuses Check; the boolean output discards the via-role metadata which
// is only meaningful to operator-facing audit code.
//
// Returns (false, nil) for an empty memberID — that's "unauthenticated
// caller", not "lookup failure" (see PermissionChecker doc comment).
func (s *Service) HasPermission(ctx context.Context, memberID, tenantID, permission string) (bool, error) {
	if memberID == "" {
		return false, nil
	}
	resp, err := s.Check(ctx, tenantID, memberID, permission)
	if err != nil {
		return false, err
	}
	return resp.Allowed, nil
}

// EnforceDestructiveEnvVar names the env flag that opts into Phase 8
// retrofit enforcement. The actual os.Getenv read lives in
// cmd/dataplane/main.go (the sanctioned env-read location per the
// lint config); main.go calls SetDestructiveEnforcement(true/false)
// once at startup based on the env value.
//
// Default off so dev / first-run flows are not broken before the
// operator-bootstrap assigns the tenant_admin role to a real user;
// production deployments MUST set it to "true".
//
// See CONVENTIONS.md §2 for the full retrofit policy.
const EnforceDestructiveEnvVar = "SAAS_RBAC_ENFORCE_DESTRUCTIVE"

// destructiveEnforcement is the global enforcement toggle. Stored as a
// uint32 + atomics so tests using t.Setenv-style overrides don't race
// against the (rare) handler reads. main.go writes once at startup;
// tests may flip via SetDestructiveEnforcement.
var destructiveEnforcement atomic.Uint32

// DestructiveEnforcementEnabled reports whether the env flag opting
// into the retrofit enforcement is set. Centralised so every module
// reads the same flag the same way (no per-handler env parsing).
func DestructiveEnforcementEnabled() bool {
	return destructiveEnforcement.Load() == 1
}

// SetDestructiveEnforcement is the startup-time setter. Called from
// cmd/dataplane/main.go with the parsed env value; tests call it
// directly when they want the gate flipped without env-var ceremony.
//
// Returns the previous value so callers (typically tests) can restore
// it via defer.
func SetDestructiveEnforcement(enabled bool) bool {
	var v uint32
	if enabled {
		v = 1
	}
	return destructiveEnforcement.Swap(v) == 1
}

// EnforceDestructive is the helper sibling handlers call before a
// retrofitted destructive operation. The contract:
//
//   - When the SAAS_RBAC_ENFORCE_DESTRUCTIVE flag is off (default), the
//     check is skipped and returns nil. The handler proceeds as before.
//   - When the flag is on, the checker is consulted with the supplied
//     (memberID, tenantID, permission). Returns ErrPermissionDenied
//     when the answer is "not allowed", otherwise nil.
//
// A nil checker is treated as "enforcement skipped" — defence in depth
// for tests that wire handlers without an authorization stack.
func EnforceDestructive(ctx context.Context, checker PermissionChecker, memberID, tenantID, permission string) error {
	if !DestructiveEnforcementEnabled() {
		return nil
	}
	if checker == nil {
		return nil
	}
	allowed, err := checker.HasPermission(ctx, memberID, tenantID, permission)
	if err != nil {
		// A lookup failure surfaces as a denied — fail closed.
		return ErrPermissionDenied
	}
	if !allowed {
		return ErrPermissionDenied
	}
	return nil
}
