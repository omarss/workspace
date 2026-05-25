package authorization_test

import (
	"context"
	"errors"
	"testing"

	"github.com/omarss/saas/internal/dataplane/authorization"
)

// Enforcer-level tests. The model file under test is the production
// rbac.conf embedded by the package; the adapter is the in-memory one
// defined in service_test.go so the matcher is exercised end-to-end
// without a live Postgres.

func TestEnforcer_RBACWithDomains_AllowsWhenRoleAssigned(t *testing.T) {
	a := newInMemoryAdapter()
	e, err := authorization.NewCasbinEnforcerFromAdapter(a)
	if err != nil {
		t.Fatalf("enforcer: %v", err)
	}
	ctx := context.Background()

	if err := e.AddRolePolicy(ctx, "role_admin", fixtureTenant, "tenant", "read"); err != nil {
		t.Fatalf("AddRolePolicy: %v", err)
	}
	if err := e.AssignRole(ctx, fixtureMemberA, "role_admin", fixtureTenant); err != nil {
		t.Fatalf("AssignRole: %v", err)
	}

	ok, via, err := e.Check(ctx, fixtureMemberA, fixtureTenant, "tenant", "read")
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	if !ok || via != "role_admin" {
		t.Fatalf("expected allowed via=role_admin, got allowed=%v via=%q", ok, via)
	}
}

func TestEnforcer_RBACWithDomains_DeniesCrossDomain(t *testing.T) {
	a := newInMemoryAdapter()
	e, err := authorization.NewCasbinEnforcerFromAdapter(a)
	if err != nil {
		t.Fatalf("enforcer: %v", err)
	}
	ctx := context.Background()

	// Grant role_admin tenant.read in tenant_A.
	if err := e.AddRolePolicy(ctx, "role_admin", fixtureTenant, "tenant", "read"); err != nil {
		t.Fatalf("AddRolePolicy: %v", err)
	}
	// Assign member_A to role_admin in tenant_A.
	if err := e.AssignRole(ctx, fixtureMemberA, "role_admin", fixtureTenant); err != nil {
		t.Fatalf("AssignRole: %v", err)
	}

	// Same subject + same obj + same act but DIFFERENT dom must be denied.
	ok, _, err := e.Check(ctx, fixtureMemberA, fixtureTenantB, "tenant", "read")
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	if ok {
		t.Fatalf("expected denied cross-domain, got allowed")
	}
}

func TestEnforcer_WildcardDomain_Refused(t *testing.T) {
	a := newInMemoryAdapter()
	e, err := authorization.NewCasbinEnforcerFromAdapter(a)
	if err != nil {
		t.Fatalf("enforcer: %v", err)
	}
	ctx := context.Background()
	if err := e.AddRolePolicy(ctx, "role_x", "*", "tenant", "read"); !errors.Is(err, authorization.ErrWildcardDomain) {
		t.Fatalf("expected ErrWildcardDomain, got %v", err)
	}
	if err := e.AssignRole(ctx, fixtureMemberA, "role_x", "*"); !errors.Is(err, authorization.ErrWildcardDomain) {
		t.Fatalf("expected ErrWildcardDomain on AssignRole, got %v", err)
	}
}

func TestEnforcer_RemoveAllRolePolicies_ClearsTenantScoped(t *testing.T) {
	a := newInMemoryAdapter()
	e, err := authorization.NewCasbinEnforcerFromAdapter(a)
	if err != nil {
		t.Fatalf("enforcer: %v", err)
	}
	ctx := context.Background()

	if err := e.AddRolePolicy(ctx, "role_x", fixtureTenant, "tenant", "read"); err != nil {
		t.Fatalf("AddRolePolicy: %v", err)
	}
	if err := e.AddRolePolicy(ctx, "role_x", fixtureTenant, "tenant", "write"); err != nil {
		t.Fatalf("AddRolePolicy: %v", err)
	}
	// A policy in a DIFFERENT tenant must NOT be touched by the clear.
	if err := e.AddRolePolicy(ctx, "role_x", fixtureTenantB, "tenant", "read"); err != nil {
		t.Fatalf("AddRolePolicy (other tenant): %v", err)
	}

	if err := e.RemoveAllRolePolicies(ctx, "role_x", fixtureTenant); err != nil {
		t.Fatalf("RemoveAllRolePolicies: %v", err)
	}
	if err := e.AssignRole(ctx, fixtureMemberA, "role_x", fixtureTenantB); err != nil {
		t.Fatalf("AssignRole: %v", err)
	}
	ok, _, _ := e.Check(ctx, fixtureMemberA, fixtureTenantB, "tenant", "read")
	if !ok {
		t.Fatalf("other-tenant policy unexpectedly cleared")
	}
}
