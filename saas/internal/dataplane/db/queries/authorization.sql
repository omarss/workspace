-- Authorization (Phase 8) queries.
--
-- Owns the role catalogue, the permission catalogue, and the member_role
-- assignment denormalisation. The casbin_rule table is owned by the Casbin
-- pgx adapter; we never query it directly from sqlc — the adapter's
-- AddPolicy / RemovePolicy / LoadPolicy is the only writer/reader.

-- name: CreateRole :one
INSERT INTO role (id, tenant_id, name, description, is_system, metadata)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING *;

-- name: GetRole :one
SELECT *
FROM role
WHERE id = $1 AND deleted_at IS NULL;

-- name: ListRolesByTenant :many
SELECT *
FROM role
WHERE tenant_id = sqlc.arg('tenant_id')
  AND deleted_at IS NULL
ORDER BY created_at DESC, id DESC
LIMIT sqlc.arg('row_limit')::int;

-- name: UpdateRole :one
UPDATE role
SET name        = COALESCE(sqlc.narg('name'),        name),
    description = COALESCE(sqlc.narg('description'), description),
    metadata    = COALESCE(sqlc.narg('metadata'),    metadata)
WHERE id = $1 AND row_seq = $2 AND deleted_at IS NULL
RETURNING *;

-- name: SoftDeleteRole :one
UPDATE role
SET deleted_at = now()
WHERE id = $1 AND row_seq = $2 AND deleted_at IS NULL
RETURNING *;

-- name: ListPermissions :many
SELECT *
FROM permission
ORDER BY module, resource_type, action;

-- name: AssignMemberRole :one
INSERT INTO member_role (member_id, role_id, tenant_id, assigned_by)
VALUES ($1, $2, $3, $4)
ON CONFLICT (member_id, role_id) DO UPDATE
    SET assigned_by = EXCLUDED.assigned_by,
        assigned_at = now()
RETURNING *;

-- name: UnassignMemberRole :execrows
DELETE FROM member_role
WHERE member_id = $1 AND role_id = $2;

-- name: ListMemberRoles :many
SELECT mr.*
FROM member_role mr
WHERE mr.member_id = $1
ORDER BY mr.assigned_at DESC;

-- name: GetMemberTenantID :one
-- Resolves the tenant a member belongs to. Used by the authorization
-- service before consulting the enforcer so cross-tenant Check requests
-- can be rejected before any policy round-trip.
SELECT tenant_id
FROM member
WHERE id = $1;
