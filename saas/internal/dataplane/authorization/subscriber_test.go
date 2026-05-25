package authorization_test

import (
	"context"
	"testing"

	"github.com/omarss/saas/internal/dataplane/authorization"
)

// TestAuthorizationTenantCreatedSubscriber_SeedsThreeRoles verifies the
// tenant.created hook plants exactly the three default system roles
// (tenant_admin, tenant_member, billing_admin), each marked is_system so
// the public DELETE path refuses removal.
func TestAuthorizationTenantCreatedSubscriber_SeedsThreeRoles(t *testing.T) {
	h := newHarness(t)
	sub := authorization.NewTenantCreatedSubscriber(h.svc)

	payload := map[string]any{
		"tenant_id": fixtureTenant,
		"slug":      "acme",
		"name":      "Acme",
	}
	if err := sub.Handle(context.Background(), payload); err != nil {
		t.Fatalf("Handle: %v", err)
	}

	// The fake repo retains every Created role; assert by Name set so
	// the test is robust to role-id randomness.
	roles := h.roles.snapshot(fixtureTenant)
	want := map[string]bool{
		"tenant_admin":  false,
		"tenant_member": false,
		"billing_admin": false,
	}
	for _, r := range roles {
		if _, ok := want[r.Name]; !ok {
			continue
		}
		want[r.Name] = true
		if !r.IsSystem {
			t.Fatalf("expected role %q to be is_system=true, got false", r.Name)
		}
	}
	for name, ok := range want {
		if !ok {
			t.Fatalf("missing default system role %q", name)
		}
	}
}

// TestAuthorizationTenantCreatedSubscriber_Idempotent verifies that
// running the subscriber twice for the same tenant_id leaves exactly
// the same three roles in place (no duplicates, no errors).
func TestAuthorizationTenantCreatedSubscriber_Idempotent(t *testing.T) {
	h := newHarness(t)
	sub := authorization.NewTenantCreatedSubscriber(h.svc)
	payload := map[string]any{"tenant_id": fixtureTenant}

	if err := sub.Handle(context.Background(), payload); err != nil {
		t.Fatalf("first Handle: %v", err)
	}
	if err := sub.Handle(context.Background(), payload); err != nil {
		t.Fatalf("second Handle (idempotency): %v", err)
	}
	roles := h.roles.snapshot(fixtureTenant)
	systemCount := 0
	names := map[string]int{}
	for _, r := range roles {
		if r.IsSystem {
			systemCount++
		}
		names[r.Name]++
	}
	if systemCount != 3 {
		t.Fatalf("expected 3 system roles after idempotent run, got %d (names=%v)", systemCount, names)
	}
	for _, want := range []string{"tenant_admin", "tenant_member", "billing_admin"} {
		if names[want] != 1 {
			t.Fatalf("expected exactly one %q role, got %d", want, names[want])
		}
	}
}

// TestAuthorizationTenantCreatedSubscriber_RejectsMissingPayload — the
// subscriber refuses to seed when tenant_id is empty rather than
// silently planting orphan system roles under an empty domain.
func TestAuthorizationTenantCreatedSubscriber_RejectsMissingPayload(t *testing.T) {
	h := newHarness(t)
	sub := authorization.NewTenantCreatedSubscriber(h.svc)
	if err := sub.Handle(context.Background(), map[string]any{}); err == nil {
		t.Fatal("expected error on missing tenant_id, got nil")
	}
}
