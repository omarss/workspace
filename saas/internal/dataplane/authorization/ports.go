package authorization

import "context"

// RoleRepo abstracts persistence for the Role catalogue. Service unit
// tests pass an in-memory fake; the pgx implementation lives in
// repo_pgx.go.
type RoleRepo interface {
	Create(ctx context.Context, r Role) (Role, error)
	Get(ctx context.Context, tenantID, roleID string) (Role, error)
	List(ctx context.Context, tenantID string, limit int) ([]Role, error)
	Update(ctx context.Context, tenantID, roleID string, expectedSeq int64, patch RolePatch) (Role, error)
	SoftDelete(ctx context.Context, tenantID, roleID string, expectedSeq int64) (Role, error)
}

// PermissionRepo is the deployment-wide permission catalogue read port.
// The catalogue is seeded by the migration; no write path exists at
// runtime.
type PermissionRepo interface {
	List(ctx context.Context) ([]Permission, error)
	Get(ctx context.Context, permissionID string) (Permission, error)
}

// MemberRoleRepo persists role assignments. The runtime enforcer reads
// the same data from casbin_rule via PolicyStore; this repo owns the
// metadata-carrying mirror table.
type MemberRoleRepo interface {
	Assign(ctx context.Context, mr MemberRole) (MemberRole, error)
	Unassign(ctx context.Context, memberID, roleID string) (bool, error)
	List(ctx context.Context, memberID string) ([]MemberRole, error)
}

// MemberLookup is the narrow read-side port used to verify a member
// belongs to the tenant claimed in a Check request. organizations'
// MemberRepo implements it via a thin adapter in cmd/dataplane.
type MemberLookup interface {
	GetMemberTenant(ctx context.Context, memberID string) (string, error)
}

// PolicyStore is the Casbin facade. Service.Check enforces against this
// interface; Service.CreateRole / AssignMemberRole mutate it. The
// enforcer.go implementation wraps casbin.Enforcer with AutoSave so
// in-memory state and the casbin_rule table stay aligned.
//
// Defence in depth: every method validates the tenant_id argument is
// non-empty and non-wildcard before touching Casbin. The DB CHECK
// constraint is the final backstop.
type PolicyStore interface {
	// Check returns (allowed, role_id_that_matched). When allowed is
	// false the role id is empty.
	Check(ctx context.Context, memberID, tenantID, resourceType, action string) (bool, string, error)

	// AddRolePolicy creates a p-row granting (resourceType, action) to
	// roleID within tenantID.
	AddRolePolicy(ctx context.Context, roleID, tenantID, resourceType, action string) error

	// RemoveRolePolicy removes a p-row.
	RemoveRolePolicy(ctx context.Context, roleID, tenantID, resourceType, action string) error

	// RemoveAllRolePolicies clears every p-row for a role inside a
	// tenant. Used by UpdateRole's set-replace semantics and by
	// DeleteRole.
	RemoveAllRolePolicies(ctx context.Context, roleID, tenantID string) error

	// AssignRole creates a g-row binding member->role within tenant.
	AssignRole(ctx context.Context, memberID, roleID, tenantID string) error

	// UnassignRole removes the g-row.
	UnassignRole(ctx context.Context, memberID, roleID, tenantID string) error
}

// EventPublisher is the outbox port. Mirrors the other modules.
type EventPublisher interface {
	Publish(ctx context.Context, eventType, tenantID string, payload map[string]any) error
}
