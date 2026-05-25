package authorization

import "errors"

// Sentinel domain errors. Translated to RFC 9457 problem responses by
// internal/platform/problem and authorization's local error mapper.
var (
	// ErrRoleNotFound — role row missing or in a different tenant.
	ErrRoleNotFound = errors.New("authorization: role not found")
	// ErrMemberNotFound — member row missing or in a different tenant.
	ErrMemberNotFound = errors.New("authorization: member not found")
	// ErrPermissionNotFound — referenced permission id not in catalogue.
	ErrPermissionNotFound = errors.New("authorization: permission not found")
	// ErrSystemRoleImmutable — caller tried to delete an is_system=true role.
	ErrSystemRoleImmutable = errors.New("authorization: system role cannot be deleted")
	// ErrETagMismatch — row_seq did not match the If-Match header.
	ErrETagMismatch = errors.New("authorization: etag mismatch")
	// ErrInvalidRoleName — role name failed validation.
	ErrInvalidRoleName = errors.New("authorization: invalid role name")
	// ErrWildcardDomain — caller attempted to set tenant_id or role name to
	// the wildcard token "*". The DB CHECK rejects the underlying row;
	// this is the service-layer guard that runs first.
	ErrWildcardDomain = errors.New("authorization: wildcard domain forbidden")
	// ErrMalformedPermission — permission string did not split into
	// (resource_type, action) at a single dot boundary.
	ErrMalformedPermission = errors.New("authorization: permission must be resource_type.action")
	// ErrBatchTooLarge — batch-check exceeded the configured limit.
	ErrBatchTooLarge = errors.New("authorization: batch too large")
	// ErrCrossTenantMember — caller asked to check a member that belongs
	// to a different tenant than the one in the request. Distinct from
	// ErrCrossTenant so the handler can map it to a more precise 403
	// problem (cross-tenant-access-denied) and the audit row carries the
	// reason.
	ErrCrossTenantMember = errors.New("authorization: member belongs to a different tenant")
	// ErrPermissionDenied — the RBAC enforcer refused the caller's
	// destructive op. Surfaced by sibling modules retrofitting the
	// Phase 8 §8.11 enforce-on-destructive path; handlers map this to a
	// 403 problem with the "forbidden" type.
	ErrPermissionDenied = errors.New("authorization: permission denied")
)
