// Package authorization is the Phase 8 RBAC module: roles, permissions,
// member-role assignments, and the synchronous Check / BatchCheck enforcer
// endpoint. Hexagonal layout mirrors organizations (Phase 7) / identity
// (Phase 5):
//
//	rbac.conf          // Casbin model file, embedded via go:embed
//	domain.go          // Role / Permission / MemberRole / CheckRequest / CheckResponse
//	ports.go           // RoleRepo / PermissionRepo / MemberRoleRepo / PolicyStore / EventPublisher
//	service.go         // application orchestration; AssertTenant precedes every read/write
//	enforcer.go        // Casbin facade — implements PolicyStore on top of casbin.Enforcer
//	repo_pgx.go        // pgx-backed RoleRepo / PermissionRepo / MemberRoleRepo
//	handler.go         // implements the generated StrictServerInterface entries
//	errors.go          // sentinel errors translated to RFC 9457 problems
//
// The Casbin model encodes RBAC-with-domains: dom = tenant_id, sub =
// "m:<member_id>" for grouping rows / role_id for policy rows, obj =
// resource_type, act = action. Wildcards in dom are forbidden by a DB
// CHECK constraint (layer 6 of the eight-layer isolation invariant) AND
// by the service layer (defence in depth).
package authorization

import (
	"time"

	"github.com/omarss/saas/internal/platform/etag"
)

// MemberSubjectPrefix is the prefix applied to member ids when used as a
// Casbin subject. The prefix keeps subjects in the grouping relation
// distinct from role names — without it, a role named "member_abc" could
// collide with a member id "member_abc" and short-circuit the matcher.
//
// Keep this constant in one place; every enforcer call site must format
// subjects via the helper FormatSubject below.
const MemberSubjectPrefix = "m:"

// FormatSubject returns the Casbin subject string for the given member
// id. Always go through this helper — handlers must never construct the
// prefix inline.
func FormatSubject(memberID string) string {
	return MemberSubjectPrefix + memberID
}

// Role is the in-memory representation of a role row. RBAC consumers see
// the catalogue through this struct; the runtime enforcer reads p-rows
// from casbin_rule directly.
type Role struct {
	ID          string
	TenantID    string
	Name        string
	Description string
	IsSystem    bool
	Metadata    map[string]string
	RowSeq      int64
	CreatedAt   time.Time
	UpdatedAt   time.Time
	DeletedAt   *time.Time
	// Permissions is the set of permission ids granted to this role. The
	// runtime authority is the casbin_rule table; the service populates
	// this slice for read paths so the API surface can render it.
	Permissions []string
}

// ETag returns the platform's Weak ETag for this role.
func (r Role) ETag() string { return etag.Format(r.RowSeq) }

// RolePatch carries optional PATCH fields. nil means "do not change this
// column". Permissions is set-replace semantics — passing a non-nil
// slice replaces the role's permission set in a single transaction.
type RolePatch struct {
	Name        *string
	Description *string
	Metadata    map[string]string
	Permissions []string
	PatchPerms  bool
}

// Permission is the in-memory representation of a permission catalogue
// row. The catalogue is deployment-wide and read-only — operators
// discover permissions via the API; modifications happen via migrations.
type Permission struct {
	ID           string
	ResourceType string
	Action       string
	Description  string
	Module       string
	IsSystem     bool
}

// Name returns the wire-friendly "resource_type.action" string. The
// Check handler uses this format for its `permission` field.
func (p Permission) Name() string {
	return p.ResourceType + "." + p.Action
}

// MemberRole is the in-memory representation of a role assignment. The
// runtime enforcer reads g-rows from casbin_rule; this struct backs the
// /v1/members/{member_id}/roles read API and the audit metadata.
type MemberRole struct {
	MemberID   string
	RoleID     string
	TenantID   string
	AssignedBy string
	AssignedAt time.Time
}

// CheckRequest is the input to Service.Check. The handler splits the
// caller-supplied "permission" string into (obj, act) at the boundary
// and populates ResourceType / Action before calling the enforcer.
type CheckRequest struct {
	MemberID     string
	TenantID     string
	ResourceType string
	Action       string
}

// CheckResponse is the output of Service.Check. ViaRole is empty when
// Allowed is false; when Allowed it carries the role_id that matched.
type CheckResponse struct {
	Allowed bool
	ViaRole string
}

// CreateRoleInput collects the fields needed to create a role. Permissions
// is the initial permission set — the service inserts one p-row per
// permission atomically with the role row.
type CreateRoleInput struct {
	Name        string
	Description string
	Permissions []string
	Metadata    map[string]string
}
