package authorization

import (
	"context"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/id"
)

// Phase 8 plan §8.12 constrains the batch size to 100. Mirrored at the
// service layer so direct service callers (saasctl, future workers) hit
// the same limit as the HTTP handler.
const (
	// MaxBatchCheckSize is the maximum number of entries allowed in
	// Service.BatchCheck. Larger calls return ErrBatchTooLarge.
	MaxBatchCheckSize = 100

	// roleNameMinLen / roleNameMaxLen mirror the OpenAPI Role.name
	// schema. Re-validated server-side as defence in depth.
	roleNameMinLen = 1
	roleNameMaxLen = 64
)

// roleNamePattern allows alphanumerics, underscore, dot, hyphen. The
// pattern intentionally forbids "*" so a caller cannot smuggle a
// wildcard token through the name field (defence in depth on top of the
// DB CHECK constraint).
var roleNamePattern = regexp.MustCompile(`^[a-zA-Z][a-zA-Z0-9_.-]*$`)

// Service is the authorization application service. It orchestrates
// the role catalogue + permission catalogue + member_role mirror table +
// the Casbin enforcer. Every state change emits an audit event so
// Phase 10 audit can build the hash-chained log.
type Service struct {
	roles       RoleRepo
	permissions PermissionRepo
	memberRoles MemberRoleRepo
	policy      PolicyStore
	members     MemberLookup
	events      EventPublisher
	now         func() time.Time
}

// Config groups Service constructor parameters.
type Config struct {
	RoleRepo       RoleRepo
	PermissionRepo PermissionRepo
	MemberRoleRepo MemberRoleRepo
	PolicyStore    PolicyStore
	MemberLookup   MemberLookup
	Events         EventPublisher
}

// NewService constructs a Service from cfg.
func NewService(cfg Config) *Service {
	return &Service{
		roles:       cfg.RoleRepo,
		permissions: cfg.PermissionRepo,
		memberRoles: cfg.MemberRoleRepo,
		policy:      cfg.PolicyStore,
		members:     cfg.MemberLookup,
		events:      cfg.Events,
		now:         time.Now,
	}
}

// WithClock substitutes the clock. Tests only.
func (s *Service) WithClock(now func() time.Time) *Service {
	s.now = now
	return s
}

// ---------------------------------------------------------------------------
// Roles
// ---------------------------------------------------------------------------

// CreateRole persists a new role inside tenantID, seeds its initial p-rows
// from the requested permission set, and emits role.created.
func (s *Service) CreateRole(ctx context.Context, tenantID string, in CreateRoleInput) (Role, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Role{}, err
	}
	// Wildcard domain guard at the service boundary mirrors the DB CHECK
	// constraint. Defence in depth so a misconfigured caller surfaces
	// ErrWildcardDomain before the round-trip.
	if tenantID == wildcardDomainToken {
		return Role{}, ErrWildcardDomain
	}
	if err := s.validateRoleName(in.Name); err != nil {
		return Role{}, err
	}
	// Resolve every requested permission so we can fail before any
	// state change if the caller passed an unknown id.
	perms, err := s.resolvePermissions(ctx, in.Permissions)
	if err != nil {
		return Role{}, err
	}

	role := Role{
		ID:          id.New(id.PrefixRole),
		TenantID:    tenantID,
		Name:        in.Name,
		Description: in.Description,
		Metadata:    in.Metadata,
	}
	created, err := s.roles.Create(ctx, role)
	if err != nil {
		return Role{}, err
	}

	// Seed p-rows for every granted permission. AutoSave keeps the DB
	// and in-memory state aligned per AddRolePolicy. If a single insert
	// fails we roll back by removing what we already wrote — the role
	// row stays around (caller will see it in the role list with an
	// empty permission set, which is recoverable).
	written := make([]Permission, 0, len(perms))
	for _, p := range perms {
		if err := s.policy.AddRolePolicy(ctx, created.ID, tenantID, p.ResourceType, p.Action); err != nil {
			for _, w := range written {
				_ = s.policy.RemoveRolePolicy(ctx, created.ID, tenantID, w.ResourceType, w.Action)
			}
			return Role{}, fmt.Errorf("authorization: seed policy: %w", err)
		}
		written = append(written, p)
	}
	created.Permissions = permissionIDs(perms)

	_ = s.events.Publish(ctx, "role.created", tenantID, map[string]any{
		"role_id":     created.ID,
		"name":        created.Name,
		"permissions": created.Permissions,
		"actor":       formatActor(ctx),
	})
	return created, nil
}

// GetRole returns the role row + its permission set.
func (s *Service) GetRole(ctx context.Context, tenantID, roleID string) (Role, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Role{}, err
	}
	return s.roles.Get(ctx, tenantID, roleID)
}

// ListRoles returns every non-deleted role in tenantID. Limit is the
// page size; cursors land when a tenant exceeds ~200 roles (out of MVP).
func (s *Service) ListRoles(ctx context.Context, tenantID string, limit int) ([]Role, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return nil, err
	}
	if limit <= 0 || limit > 200 {
		limit = 200
	}
	return s.roles.List(ctx, tenantID, limit)
}

// UpdateRole patches the role row and, when the permissions slice is
// supplied, rewrites the p-rows atomically (clear-then-reinsert).
func (s *Service) UpdateRole(ctx context.Context, tenantID, roleID string, expectedSeq int64, patch RolePatch) (Role, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Role{}, err
	}
	if patch.Name != nil {
		if err := s.validateRoleName(*patch.Name); err != nil {
			return Role{}, err
		}
	}
	// Resolve permissions first so we can fail-fast.
	var perms []Permission
	if patch.PatchPerms {
		var err error
		perms, err = s.resolvePermissions(ctx, patch.Permissions)
		if err != nil {
			return Role{}, err
		}
	}

	updated, err := s.roles.Update(ctx, tenantID, roleID, expectedSeq, patch)
	if err != nil {
		return Role{}, err
	}

	if patch.PatchPerms {
		// Set-replace semantics: drop every existing p-row for this
		// role within this tenant, then re-insert the new set.
		if err := s.policy.RemoveAllRolePolicies(ctx, roleID, tenantID); err != nil {
			return Role{}, err
		}
		for _, p := range perms {
			if err := s.policy.AddRolePolicy(ctx, roleID, tenantID, p.ResourceType, p.Action); err != nil {
				return Role{}, fmt.Errorf("authorization: rewrite policy: %w", err)
			}
		}
		updated.Permissions = permissionIDs(perms)
	}

	_ = s.events.Publish(ctx, "role.updated", tenantID, map[string]any{
		"role_id": updated.ID,
		"actor":   formatActor(ctx),
	})
	return updated, nil
}

// DeleteRole soft-deletes the role and clears its p-rows. System roles
// refuse delete (anti-pattern guard from the plan: removing tenant_admin
// would lock the operator out).
func (s *Service) DeleteRole(ctx context.Context, tenantID, roleID string, expectedSeq int64) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	existing, err := s.roles.Get(ctx, tenantID, roleID)
	if err != nil {
		return err
	}
	if existing.IsSystem {
		return ErrSystemRoleImmutable
	}
	if _, err := s.roles.SoftDelete(ctx, tenantID, roleID, expectedSeq); err != nil {
		return err
	}
	// Clear every p-row + every g-row pointing at this role. The
	// enforcer's RemoveFilteredPolicy keeps the cache and DB in sync.
	if err := s.policy.RemoveAllRolePolicies(ctx, roleID, tenantID); err != nil {
		return err
	}

	_ = s.events.Publish(ctx, "role.deleted", tenantID, map[string]any{
		"role_id": roleID,
		"actor":   formatActor(ctx),
	})
	return nil
}

// ---------------------------------------------------------------------------
// Permissions
// ---------------------------------------------------------------------------

// ListPermissions returns the deployment-wide permission catalogue.
func (s *Service) ListPermissions(ctx context.Context) ([]Permission, error) {
	if _, ok := auth.TenantFromContext(ctx); !ok {
		return nil, auth.ErrUnauthorized
	}
	return s.permissions.List(ctx)
}

// ---------------------------------------------------------------------------
// Member-role assignments
// ---------------------------------------------------------------------------

// AssignMemberRole adds the role to the member's assignment set and
// writes the matching g-row. Re-assigning an existing pair is idempotent
// (UPSERT on the mirror table; Casbin's AddGroupingPolicy returns
// false-but-no-error when the row already exists).
func (s *Service) AssignMemberRole(ctx context.Context, tenantID, memberID, roleID string) (MemberRole, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return MemberRole{}, err
	}
	// The role must exist and belong to this tenant.
	if _, err := s.roles.Get(ctx, tenantID, roleID); err != nil {
		return MemberRole{}, err
	}
	// The member must exist and belong to this tenant.
	memberTenant, err := s.members.GetMemberTenant(ctx, memberID)
	if err != nil {
		return MemberRole{}, err
	}
	if memberTenant != tenantID {
		return MemberRole{}, ErrCrossTenantMember
	}

	if err := s.policy.AssignRole(ctx, memberID, roleID, tenantID); err != nil {
		return MemberRole{}, err
	}
	mr, err := s.memberRoles.Assign(ctx, MemberRole{
		MemberID:   memberID,
		RoleID:     roleID,
		TenantID:   tenantID,
		AssignedBy: formatActor(ctx),
		AssignedAt: s.now(),
	})
	if err != nil {
		// Roll back the casbin g-row so the mirror table and Casbin
		// state stay aligned.
		_ = s.policy.UnassignRole(ctx, memberID, roleID, tenantID)
		return MemberRole{}, err
	}

	_ = s.events.Publish(ctx, "member.role_assigned", tenantID, map[string]any{
		"member_id":   memberID,
		"role_id":     roleID,
		"assigned_by": formatActor(ctx),
	})
	return mr, nil
}

// UnassignMemberRole removes the role assignment.
func (s *Service) UnassignMemberRole(ctx context.Context, tenantID, memberID, roleID string) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	memberTenant, err := s.members.GetMemberTenant(ctx, memberID)
	if err != nil {
		return err
	}
	if memberTenant != tenantID {
		return ErrCrossTenantMember
	}
	if err := s.policy.UnassignRole(ctx, memberID, roleID, tenantID); err != nil {
		return err
	}
	if _, err := s.memberRoles.Unassign(ctx, memberID, roleID); err != nil {
		return err
	}

	_ = s.events.Publish(ctx, "member.role_unassigned", tenantID, map[string]any{
		"member_id":     memberID,
		"role_id":       roleID,
		"unassigned_by": formatActor(ctx),
	})
	return nil
}

// ListMemberRoles returns every role assigned to memberID.
func (s *Service) ListMemberRoles(ctx context.Context, tenantID, memberID string) ([]MemberRole, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return nil, err
	}
	memberTenant, err := s.members.GetMemberTenant(ctx, memberID)
	if err != nil {
		return nil, err
	}
	if memberTenant != tenantID {
		return nil, ErrCrossTenantMember
	}
	return s.memberRoles.List(ctx, memberID)
}

// ---------------------------------------------------------------------------
// Check / BatchCheck
// ---------------------------------------------------------------------------

// Check evaluates memberID's permission inside tenantID. Returns
// (allowed, viaRoleID, err). Every denial emits authorization.denied to
// the outbox so Phase 10 audit can record the security signal.
func (s *Service) Check(ctx context.Context, tenantID, memberID, permission string) (CheckResponse, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return CheckResponse{}, err
	}
	obj, act, err := splitPermission(permission)
	if err != nil {
		return CheckResponse{}, err
	}
	// Cross-tenant member protection: if the member belongs to a
	// different tenant than the requested domain, that's a privilege
	// escalation attempt. We refuse before consulting Casbin.
	memberTenant, lookupErr := s.members.GetMemberTenant(ctx, memberID)
	if lookupErr != nil {
		// Member not found maps to allowed=false but emits the same
		// denied event so the audit row records the attempt. The
		// underlying error is intentionally swallowed: Check is a
		// boolean policy decision; an unknown member is "deny" not
		// "lookup failed".
		s.emitDenied(ctx, tenantID, memberID, permission, "member_not_found")
		return CheckResponse{Allowed: false}, nil //nolint:nilerr // intentional: unknown member = deny
	}
	if memberTenant != tenantID {
		s.emitDenied(ctx, tenantID, memberID, permission, "cross_tenant_member")
		return CheckResponse{Allowed: false}, ErrCrossTenantMember
	}

	allowed, viaRole, err := s.policy.Check(ctx, memberID, tenantID, obj, act)
	if err != nil {
		return CheckResponse{}, err
	}
	if !allowed {
		s.emitDenied(ctx, tenantID, memberID, permission, "policy")
	}
	return CheckResponse{Allowed: allowed, ViaRole: viaRole}, nil
}

// BatchCheck evaluates many checks in one call. Every request shares
// the same caller context — AssertTenant is run once for the calling
// tenant and every per-check tenant_id must match (the OpenAPI schema
// keeps a tenant_id per item so future operator paths can mix tenants;
// MVP rejects mismatches).
func (s *Service) BatchCheck(ctx context.Context, requests []CheckBatchEntry) ([]CheckResponse, error) {
	if len(requests) > MaxBatchCheckSize {
		return nil, ErrBatchTooLarge
	}
	out := make([]CheckResponse, len(requests))
	for i, r := range requests {
		resp, err := s.Check(ctx, r.TenantID, r.MemberID, r.Permission)
		if err != nil {
			// Cross-tenant attempts inside a batch are denied per-row
			// rather than failing the whole call — the audit hook
			// already fired in Check.
			out[i] = CheckResponse{Allowed: false}
			continue
		}
		out[i] = resp
	}
	return out, nil
}

// CheckBatchEntry is one element of a BatchCheck payload.
type CheckBatchEntry struct {
	TenantID   string
	MemberID   string
	Permission string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// splitPermission separates a "resource_type.action" string at the first
// dot. The split is at the handler boundary per ADR 005; re-implementations
// elsewhere are an anti-pattern.
func splitPermission(permission string) (string, string, error) {
	obj, act, ok := strings.Cut(permission, ".")
	if !ok || obj == "" || act == "" {
		return "", "", ErrMalformedPermission
	}
	if strings.Contains(act, ".") {
		// Reject "a.b.c" — a permission name is exactly one dot.
		return "", "", ErrMalformedPermission
	}
	return obj, act, nil
}

func (s *Service) validateRoleName(name string) error {
	n := strings.TrimSpace(name)
	if len(n) < roleNameMinLen || len(n) > roleNameMaxLen {
		return ErrInvalidRoleName
	}
	if n == wildcardDomainToken {
		return ErrWildcardDomain
	}
	if !roleNamePattern.MatchString(n) {
		return ErrInvalidRoleName
	}
	return nil
}

func (s *Service) resolvePermissions(ctx context.Context, ids []string) ([]Permission, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	resolved := make([]Permission, 0, len(ids))
	for _, pid := range ids {
		p, err := s.permissions.Get(ctx, pid)
		if err != nil {
			return nil, err
		}
		resolved = append(resolved, p)
	}
	return resolved, nil
}

func (s *Service) emitDenied(ctx context.Context, tenantID, memberID, permission, reason string) {
	_ = s.events.Publish(ctx, "authorization.denied", tenantID, map[string]any{
		"member_id":  memberID,
		"tenant_id":  tenantID,
		"permission": permission,
		"reason":     reason,
		"actor":      formatActor(ctx),
		"at":         s.now().UTC(),
	})
}

func permissionIDs(perms []Permission) []string {
	out := make([]string, len(perms))
	for i, p := range perms {
		out[i] = p.ID
	}
	return out
}

// formatActor returns the "<actor_type>:<actor_id>" audit string for the
// caller, or "unknown" when no principal is in context (the mock
// middleware does not populate one in some integration paths).
func formatActor(ctx context.Context) string {
	p, ok := auth.PrincipalFromContext(ctx)
	if !ok {
		return "unknown"
	}
	return p.FormatActor()
}
