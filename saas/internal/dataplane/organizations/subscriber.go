package organizations

import (
	"context"
	"errors"
	"fmt"
	"log/slog"

	"github.com/omarss/saas/internal/platform/auth"
)

// TenantCreatedSubscriber listens for the tenant.created outbox event
// (or a same-process call from the tenancy service) and auto-creates the
// default organization in the new tenant.
//
// Phase 7 ships this as a synchronous call from a tenant.created event
// handler in cmd/dataplane. A future in-process EventBus (Phase 10
// audit) will subscribe via the same hook, so the contract is event-
// shaped rather than direct.
type TenantCreatedSubscriber struct {
	svc *Service
}

// NewTenantCreatedSubscriber wires the subscriber.
func NewTenantCreatedSubscriber(svc *Service) *TenantCreatedSubscriber {
	return &TenantCreatedSubscriber{svc: svc}
}

// Handle processes a tenant.created event payload. The payload schema
// matches the one emitted by tenancy.Service.Create:
//
//	{ "tenant_id": "tenant_...", "slug": "...", "name": "..." }
//
// Idempotent — AutoCreateDefault returns the existing default org when
// the row already exists (back-fill safety).
func (s *TenantCreatedSubscriber) Handle(ctx context.Context, payload map[string]any) error {
	tenantID, _ := payload["tenant_id"].(string)
	if tenantID == "" {
		return errors.New("organizations: tenant.created payload missing tenant_id")
	}
	// Bind the tenant context so the auth.AssertTenant inside the
	// service does not reject a system-initiated call. The subscriber
	// is system-actor.
	ctx = auth.WithPrincipal(ctx, auth.Principal{
		ActorType: auth.ActorSystem,
		ActorID:   "system",
		TenantID:  tenantID,
	})
	o, err := s.svc.AutoCreateDefault(ctx, tenantID)
	if err != nil {
		return fmt.Errorf("organizations: auto-create default org for %s: %w", tenantID, err)
	}
	slog.Info(
		"auto-created default organization",
		"tenant_id", tenantID,
		"organization_id", o.ID,
	)
	return nil
}
