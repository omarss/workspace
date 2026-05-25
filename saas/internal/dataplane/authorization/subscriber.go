package authorization

import (
	"context"
	"errors"
	"fmt"
	"log/slog"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/id"
)

// systemRoleSeed groups a single default system role with its initial
// permission set. The seeding catalogue is intentionally co-located with
// the subscriber so the contract between "permissions migrated in
// migrations/dataplane/000006_authorization.up.sql" and "roles created
// for every new tenant" lives in one file.
//
// Permission strings here MUST match the resource_type.action pairs
// seeded by the migration; mismatches surface as ErrPermissionNotFound
// at seeding time (defence in depth via Service.resolvePermissions in
// createSystemRole below).
type systemRoleSeed struct {
	Name        string
	Description string
	// Permissions is the set of permission ids (NOT the
	// "resource_type.action" wire form). Mapping from name → id is
	// stable because the migration seeds with fixed ids of the form
	// perm_<resource>_<action>.
	Permissions []string
}

// defaultSystemRoles is the catalogue of roles seeded for every new
// tenant. Adding a new role here automatically applies to every
// tenant.created event from that point on; existing tenants do NOT
// back-fill — they get the new role the next time the subscriber runs,
// which is only on a fresh tenant.created. Operators back-filling
// historical tenants must run a one-shot migration job.
var defaultSystemRoles = []systemRoleSeed{
	{
		Name:        "tenant_admin",
		Description: "Full administrative access within the tenant.",
		Permissions: []string{
			"perm_tenant_read",
			"perm_tenant_write",
			"perm_organization_read",
			"perm_organization_write",
			"perm_organization_delete",
			"perm_member_read",
			"perm_member_write",
			"perm_invitation_read",
			"perm_invitation_write",
			"perm_user_read",
			"perm_user_write",
			"perm_user_disable",
			"perm_role_read",
			"perm_role_write",
			"perm_role_delete",
			"perm_role_assign",
			"perm_apikey_read",
			"perm_apikey_write",
			"perm_audit_read",
			"perm_notification_read",
			"perm_notification_send",
			"perm_notification_channel_read",
			"perm_notification_channel_write",
		},
	},
	{
		Name:        "tenant_member",
		Description: "Read-only access to tenant resources.",
		Permissions: []string{
			"perm_tenant_read",
			"perm_organization_read",
			"perm_member_read",
			"perm_invitation_read",
			"perm_user_read",
			"perm_role_read",
			"perm_apikey_read",
			"perm_audit_read",
			"perm_notification_read",
			"perm_notification_channel_read",
		},
	},
	{
		// billing_admin is a v1 placeholder. Phase 13 (billing) adds
		// billing-specific permissions; until then this role exists so
		// the operator-bootstrap flow can assign it without later
		// re-engineering the seeding step.
		Name:        "billing_admin",
		Description: "Billing operations within the tenant (v1 fills out the actions).",
		Permissions: []string{
			"perm_tenant_read",
		},
	},
}

// TenantCreatedSubscriber listens for the tenant.created outbox event
// and seeds the default system roles for the new tenant. Mirrors the
// Phase 7 organizations.TenantCreatedSubscriber pattern (synchronous
// in-process fan-out today; a real Phase 10 EventBus subscriber pool
// will route the same Handle method later).
//
// Idempotent: a tenant whose system roles already exist is a no-op so
// the subscriber is safe to re-run (back-fill, retried tenant.created
// after a transient subscriber crash, etc.).
type TenantCreatedSubscriber struct {
	svc *Service
}

// NewTenantCreatedSubscriber wires the subscriber over the authorization
// service.
func NewTenantCreatedSubscriber(svc *Service) *TenantCreatedSubscriber {
	return &TenantCreatedSubscriber{svc: svc}
}

// Handle processes a tenant.created payload. The payload schema matches
// the one emitted by tenancy.Service.Create:
//
//	{ "tenant_id": "tenant_...", "slug": "...", "name": "..." }
//
// Returns an error when seeding fails. The outer fan-out (cmd/dataplane)
// logs but does not propagate the error: subscribers are best-effort
// reactive layers; the outbox event remains the audit log of record.
func (s *TenantCreatedSubscriber) Handle(ctx context.Context, payload map[string]any) error {
	tenantID, _ := payload["tenant_id"].(string)
	if tenantID == "" {
		return errors.New("authorization: tenant.created payload missing tenant_id")
	}
	// Bind tenant context so AssertTenant inside the service succeeds —
	// the subscriber runs as the platform system actor, distinguishable
	// in audit rows from a user-initiated CreateRole call.
	ctx = auth.WithPrincipal(ctx, auth.Principal{
		ActorType: auth.ActorSystem,
		ActorID:   "system",
		TenantID:  tenantID,
	})

	// List once and build a name → role-id lookup. Skipping seeds that
	// already exist makes Handle idempotent on retry / back-fill.
	existing, err := s.svc.ListRoles(ctx, tenantID, len(defaultSystemRoles)*2)
	if err != nil {
		return fmt.Errorf("authorization: list roles for seed: %w", err)
	}
	byName := make(map[string]struct{}, len(existing))
	for _, r := range existing {
		byName[r.Name] = struct{}{}
	}

	for _, seed := range defaultSystemRoles {
		if _, ok := byName[seed.Name]; ok {
			slog.Debug("authorization: system role already present, skipping",
				"tenant_id", tenantID, "role", seed.Name)
			continue
		}
		if _, err := s.svc.createSystemRole(ctx, tenantID, seed); err != nil {
			return fmt.Errorf("authorization: seed system role %q for %s: %w",
				seed.Name, tenantID, err)
		}
		slog.Info("authorization: seeded system role",
			"tenant_id", tenantID, "role", seed.Name)
	}
	return nil
}

// createSystemRole is the privileged seeding helper invoked by the
// TenantCreatedSubscriber during tenant bootstrap. It bypasses the
// public CreateRole surface so the is_system flag can be set true — the
// flag prevents subsequent DELETE attempts via the HTTP API (the public
// CreateRole intentionally has no IsSystem field for that reason).
//
// AssertTenant is still called by ListPermissions / resolvePermissions
// downstream; the caller MUST have bound a Principal whose TenantID
// matches tenantID (the Subscriber.Handle path does so).
func (s *Service) createSystemRole(ctx context.Context, tenantID string, seed systemRoleSeed) (Role, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Role{}, err
	}
	if tenantID == wildcardDomainToken {
		return Role{}, ErrWildcardDomain
	}
	perms, err := s.resolvePermissions(ctx, seed.Permissions)
	if err != nil {
		return Role{}, err
	}
	role := Role{
		ID:          id.New(id.PrefixRole),
		TenantID:    tenantID,
		Name:        seed.Name,
		Description: seed.Description,
		IsSystem:    true,
	}
	created, err := s.roles.Create(ctx, role)
	if err != nil {
		return Role{}, err
	}
	// Seed p-rows for every granted permission. On a single failure we
	// roll back what we already wrote — the role row stays around (the
	// next Handle call will see it in the name lookup and skip).
	written := make([]Permission, 0, len(perms))
	for _, p := range perms {
		if err := s.policy.AddRolePolicy(ctx, created.ID, tenantID, p.ResourceType, p.Action); err != nil {
			for _, w := range written {
				_ = s.policy.RemoveRolePolicy(ctx, created.ID, tenantID, w.ResourceType, w.Action)
			}
			return Role{}, fmt.Errorf("authorization: seed system policy: %w", err)
		}
		written = append(written, p)
	}
	created.Permissions = permissionIDs(perms)

	_ = s.events.Publish(ctx, "role.created", tenantID, map[string]any{
		"role_id":     created.ID,
		"name":        created.Name,
		"permissions": created.Permissions,
		"is_system":   true,
		"actor":       formatActor(ctx),
	})
	return created, nil
}
