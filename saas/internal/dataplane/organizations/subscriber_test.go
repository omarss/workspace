package organizations_test

import (
	"context"
	"testing"

	"github.com/omarss/saas/internal/dataplane/organizations"
)

// TestTenantCreatedSubscriber_AutoCreatesDefaultOrg — the Phase 7 plan
// hard-requires a default org per tenant. The subscriber is idempotent
// (back-fill safety) so a duplicate event resolves to the same org id.
func TestTenantCreatedSubscriber_AutoCreatesDefaultOrg(t *testing.T) {
	h := newHarness(t)
	sub := organizations.NewTenantCreatedSubscriber(h.svc)

	payload := map[string]any{
		"tenant_id": fixtureTenant,
		"slug":      "acme",
		"name":      "Acme",
	}
	if err := sub.Handle(context.Background(), payload); err != nil {
		t.Fatalf("first handle: %v", err)
	}
	// Re-running the subscriber must NOT error (back-fill safety).
	if err := sub.Handle(context.Background(), payload); err != nil {
		t.Fatalf("second handle (idempotency): %v", err)
	}
	// The repository should hold exactly one organization for the tenant.
	orgs, _, err := h.orgRepo.List(context.Background(), fixtureTenant, 25, nil)
	if err != nil {
		t.Fatalf("list orgs: %v", err)
	}
	if len(orgs) != 1 {
		t.Fatalf("expected 1 default org after two handles, got %d", len(orgs))
	}
	if orgs[0].Slug != organizations.DefaultOrganizationSlug {
		t.Fatalf("expected slug %q, got %q", organizations.DefaultOrganizationSlug, orgs[0].Slug)
	}
}

func TestTenantCreatedSubscriber_RejectsMissingPayload(t *testing.T) {
	h := newHarness(t)
	sub := organizations.NewTenantCreatedSubscriber(h.svc)
	err := sub.Handle(context.Background(), map[string]any{})
	if err == nil {
		t.Fatal("expected error on missing tenant_id, got nil")
	}
}
