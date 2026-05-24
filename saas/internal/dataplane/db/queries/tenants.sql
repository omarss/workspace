-- name: CreateTenant :one
INSERT INTO tenant (id, slug, name, metadata)
VALUES ($1, $2, $3, $4)
RETURNING id, slug, name, status, default_organization_id, metadata, row_seq, created_at, updated_at, deleted_at;

-- name: GetTenant :one
SELECT id, slug, name, status, default_organization_id, metadata, row_seq, created_at, updated_at, deleted_at
FROM tenant
WHERE id = $1 AND deleted_at IS NULL;

-- name: GetTenantBySlug :one
SELECT id, slug, name, status, default_organization_id, metadata, row_seq, created_at, updated_at, deleted_at
FROM tenant
WHERE slug = $1 AND deleted_at IS NULL;

-- name: ListTenants :many
-- Keyset pagination on (created_at DESC, id DESC). Cursor passes the last
-- emitted row's pair; the +1 returned row signals has_more (the handler
-- trims and emits the cursor for the trailing row).
SELECT id, slug, name, status, default_organization_id, metadata, row_seq, created_at, updated_at, deleted_at
FROM tenant
WHERE deleted_at IS NULL
  AND (
    sqlc.narg('cursor_created_at')::timestamptz IS NULL
    OR (created_at, id) < (sqlc.narg('cursor_created_at')::timestamptz, sqlc.narg('cursor_id')::text)
  )
ORDER BY created_at DESC, id DESC
LIMIT sqlc.arg('row_limit')::int;

-- name: UpdateTenant :one
-- Optimistic concurrency: expected_row_seq must match the current row_seq,
-- otherwise zero rows are returned and the service raises ErrETagMismatch.
UPDATE tenant
SET
    name     = COALESCE(sqlc.narg('name'),     name),
    status   = COALESCE(sqlc.narg('status'),   status),
    metadata = COALESCE(sqlc.narg('metadata'), metadata)
WHERE id = $1
  AND row_seq = $2
  AND deleted_at IS NULL
RETURNING id, slug, name, status, default_organization_id, metadata, row_seq, created_at, updated_at, deleted_at;

-- name: SoftDeleteTenant :one
UPDATE tenant
SET status     = 'deleted',
    deleted_at = now()
WHERE id = $1
  AND row_seq = $2
  AND deleted_at IS NULL
RETURNING id, slug, name, status, default_organization_id, metadata, row_seq, created_at, updated_at, deleted_at;

-- name: SetDefaultOrganization :exec
UPDATE tenant SET default_organization_id = $2 WHERE id = $1;
