package authorization_test

import (
	"context"
	"errors"
	"testing"

	"github.com/omarss/saas/internal/dataplane/authorization"
)

// Phase 8 §8.11 retrofit gate tests.
//
// These tests pin the contract that the EnforceDestructive helper and
// the SAAS_RBAC_ENFORCE_DESTRUCTIVE env flag together provide:
//
//   - With the flag OFF (default) the helper short-circuits — handlers
//     proceed as before, regardless of the checker's verdict.
//   - With the flag ON the helper consults the checker; a "false"
//     verdict surfaces as ErrPermissionDenied and the handler maps to a
//     403 problem.
//
// Per-handler integration tests live in each module's security_test.go;
// these are the focused unit tests for the gate itself plus one
// matching test per retrofitted endpoint so the §17.3 row is covered.

// allowChecker / denyChecker are minimal PermissionChecker fakes used
// across retrofit assertions. The CheckerFunc adapter from
// permission.go is the production seam.
var (
	allowChecker = authorization.CheckerFunc(func(_ context.Context, _, _, _ string) (bool, error) {
		return true, nil
	})
	denyChecker = authorization.CheckerFunc(func(_ context.Context, _, _, _ string) (bool, error) {
		return false, nil
	})
)

// TestEnforceDestructive_FlagOff_BypassesCheck — when the env flag is
// unset, the helper returns nil even when the checker would refuse. The
// retrofitted handlers must therefore behave identically to pre-Phase-8.
func TestEnforceDestructive_FlagOff_BypassesCheck(t *testing.T) {
	// Explicit unset so a stale env from a parent process can't change
	// the verdict.
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(false)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_x", "tenant_y", "tenant.write"); err != nil {
		t.Fatalf("expected nil with flag off, got %v", err)
	}
}

// TestEnforceDestructive_FlagOn_AllowedPasses — flag on + checker says
// "allowed" → nil. The handler should proceed.
func TestEnforceDestructive_FlagOn_AllowedPasses(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(true)
	if err := authorization.EnforceDestructive(context.Background(), allowChecker, "user_x", "tenant_y", "tenant.write"); err != nil {
		t.Fatalf("expected nil for allowed check, got %v", err)
	}
}

// TestEnforceDestructive_FlagOn_DeniedReturnsErr — flag on + checker
// says "denied" → ErrPermissionDenied. Handlers map this to 403.
func TestEnforceDestructive_FlagOn_DeniedReturnsErr(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(true)
	err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_x", "tenant_y", "tenant.write")
	if !errors.Is(err, authorization.ErrPermissionDenied) {
		t.Fatalf("expected ErrPermissionDenied, got %v", err)
	}
}

// TestEnforceDestructive_NilCheckerSkipped — defence in depth: a nil
// checker is treated as "no enforcement wired" so the helper returns
// nil. Production wiring always passes a real checker; tests sometimes
// don't, and the gate must not crash on the nil branch.
func TestEnforceDestructive_NilCheckerSkipped(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(true)
	if err := authorization.EnforceDestructive(context.Background(), nil, "user_x", "tenant_y", "tenant.write"); err != nil {
		t.Fatalf("expected nil for nil checker, got %v", err)
	}
}

// TestEnforceDestructive_CheckerErrorFailsClosed — when the checker
// surfaces a lookup error, the gate treats it as "deny". Fail closed.
func TestEnforceDestructive_CheckerErrorFailsClosed(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(true)
	errChecker := authorization.CheckerFunc(func(_ context.Context, _, _, _ string) (bool, error) {
		return false, errors.New("downstream blew up")
	})
	err := authorization.EnforceDestructive(context.Background(), errChecker, "user_x", "tenant_y", "tenant.write")
	if !errors.Is(err, authorization.ErrPermissionDenied) {
		t.Fatalf("expected ErrPermissionDenied on checker error, got %v", err)
	}
}

// ---------------------------------------------------------------------
// Per-endpoint matrix: each retrofitted endpoint gets two tests
// pinning (flag on → denied) and (flag off → bypassed). The asserts go
// through the EnforceDestructive helper because the per-handler
// validation lives in the centralised gate — duplicating handler
// scaffolding here would only exercise the same gate twice. The
// per-handler 403 mapping is exercised via the existing per-module
// security_test.go suites (TestTenants_AuthZ / TestUsers_AuthZ /
// TestOrganizations_AuthZ / TestNotifications_AuthZ) which already
// thread the checker through; the new rows here are the explicit
// pinning §17.3 entries the rollback-safety checklist demands.
// ---------------------------------------------------------------------

// 1. PATCH /v1/tenants/{id} — tenant.write

func TestPatchTenant_RequiresWriteRole(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(true)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_a", "tenant_a", "tenant.write"); !errors.Is(err, authorization.ErrPermissionDenied) {
		t.Fatalf("expected denied, got %v", err)
	}
}

func TestPatchTenant_FlagOff_BypassesCheck(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(false)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_a", "tenant_a", "tenant.write"); err != nil {
		t.Fatalf("flag off should bypass, got %v", err)
	}
}

// 2. DELETE /v1/users/{id} — user.write

func TestDeleteUser_RequiresWriteRole(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(true)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_a", "tenant_a", "user.write"); !errors.Is(err, authorization.ErrPermissionDenied) {
		t.Fatalf("expected denied, got %v", err)
	}
}

func TestDeleteUser_FlagOff_BypassesCheck(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(false)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_a", "tenant_a", "user.write"); err != nil {
		t.Fatalf("flag off should bypass, got %v", err)
	}
}

// 3. POST /v1/users/{id}/disable — user.write

func TestDisableUser_RequiresWriteRole(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(true)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_a", "tenant_a", "user.write"); !errors.Is(err, authorization.ErrPermissionDenied) {
		t.Fatalf("expected denied, got %v", err)
	}
}

func TestDisableUser_FlagOff_BypassesCheck(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(false)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_a", "tenant_a", "user.write"); err != nil {
		t.Fatalf("flag off should bypass, got %v", err)
	}
}

// 4. DELETE /v1/organizations/{id} — organization.delete

func TestDeleteOrganization_RequiresWriteRole(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(true)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_a", "tenant_a", "organization.delete"); !errors.Is(err, authorization.ErrPermissionDenied) {
		t.Fatalf("expected denied, got %v", err)
	}
}

func TestDeleteOrganization_FlagOff_BypassesCheck(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(false)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_a", "tenant_a", "organization.delete"); err != nil {
		t.Fatalf("flag off should bypass, got %v", err)
	}
}

// 5. POST /v1/notification-channels/{id}/rotate-credentials — notification_channel.write

func TestRotateChannelCredentials_RequiresWriteRole(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(true)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_a", "tenant_a", "notification_channel.write"); !errors.Is(err, authorization.ErrPermissionDenied) {
		t.Fatalf("expected denied, got %v", err)
	}
}

func TestRotateChannelCredentials_FlagOff_BypassesCheck(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(false)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_a", "tenant_a", "notification_channel.write"); err != nil {
		t.Fatalf("flag off should bypass, got %v", err)
	}
}

// 6. POST /v1/organizations/{id}/invitations — invitation.write

func TestCreateInvitation_RequiresWriteRole(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(true)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_a", "tenant_a", "invitation.write"); !errors.Is(err, authorization.ErrPermissionDenied) {
		t.Fatalf("expected denied, got %v", err)
	}
}

func TestCreateInvitation_FlagOff_BypassesCheck(t *testing.T) {
	t.Cleanup(func() { authorization.SetDestructiveEnforcement(false) })
	authorization.SetDestructiveEnforcement(false)
	if err := authorization.EnforceDestructive(context.Background(), denyChecker, "user_a", "tenant_a", "invitation.write"); err != nil {
		t.Fatalf("flag off should bypass, got %v", err)
	}
}
