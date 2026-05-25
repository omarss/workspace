-- Organizations + Members + Invitations queries (Phase 7).
--
-- The repository (internal/dataplane/organizations/repo_pgx.go) is
-- responsible for:
--   * Running crypto.EncryptPIIFieldsStrict on the Invitation domain
--     struct BEFORE binding parameters (invitee_email envelope columns).
--   * Verifying env.KID == deployment_id on every Get / List hydrate
--     before invoking DecryptField.
--   * Computing the HMAC-SHA256 invitee_email_lookup_hash via the same
--     hasher used by Identity (deployment-scoped key in OpenBao KV).

-- name: CreateOrganization :one
INSERT INTO organization (id, tenant_id, slug, name, status, metadata)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING *;

-- name: GetOrganization :one
SELECT *
FROM organization
WHERE id = $1 AND deleted_at IS NULL;

-- name: GetOrganizationBySlug :one
SELECT *
FROM organization
WHERE tenant_id = $1 AND slug = $2 AND deleted_at IS NULL;

-- name: ListOrganizationsByTenant :many
-- Keyset pagination on (created_at DESC, id DESC). row_limit is limit+1
-- so the caller can detect has_more.
SELECT *
FROM organization
WHERE tenant_id = sqlc.arg('tenant_id')
  AND deleted_at IS NULL
  AND (
    sqlc.narg('cursor_created_at')::timestamptz IS NULL
    OR (created_at, id) < (sqlc.narg('cursor_created_at')::timestamptz, sqlc.narg('cursor_id')::text)
  )
ORDER BY created_at DESC, id DESC
LIMIT sqlc.arg('row_limit')::int;

-- name: UpdateOrganization :one
UPDATE organization
SET
    name     = COALESCE(sqlc.narg('name'),     name),
    status   = COALESCE(sqlc.narg('status'),   status),
    metadata = COALESCE(sqlc.narg('metadata'), metadata)
WHERE id = $1
  AND row_seq = $2
  AND deleted_at IS NULL
RETURNING *;

-- name: SoftDeleteOrganization :one
UPDATE organization
SET status = 'deleted', deleted_at = now()
WHERE id = $1
  AND row_seq = $2
  AND deleted_at IS NULL
RETURNING *;

-- name: CreateMember :one
INSERT INTO member (id, tenant_id, organization_id, user_id, role_id, status, metadata)
VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING *;

-- name: GetMember :one
SELECT *
FROM member
WHERE id = $1;

-- name: ListMembersByOrganization :many
SELECT *
FROM member
WHERE organization_id = sqlc.arg('organization_id')
  AND status != 'removed'
  AND (
    sqlc.narg('cursor_joined_at')::timestamptz IS NULL
    OR (joined_at, id) < (sqlc.narg('cursor_joined_at')::timestamptz, sqlc.narg('cursor_id')::text)
  )
ORDER BY joined_at DESC, id DESC
LIMIT sqlc.arg('row_limit')::int;

-- name: GetMemberByUser :one
SELECT *
FROM member
WHERE organization_id = $1 AND user_id = $2 AND status = 'active';

-- name: UpdateMemberRole :one
UPDATE member
SET role_id = sqlc.narg('role_id')
WHERE id = $1 AND row_seq = $2 AND status = 'active'
RETURNING *;

-- name: RemoveMember :one
UPDATE member
SET status = 'removed', removed_at = now()
WHERE id = $1 AND row_seq = $2 AND status = 'active'
RETURNING *;

-- name: CreateInvitation :one
INSERT INTO invitation (
    id, tenant_id, organization_id,
    invitee_email_lookup_hash, invitee_email_ciphertext, invitee_email_wrapped_dek,
    invitee_email_nonce, invitee_email_kid, invitee_email_key_version,
    token_hash, token_prefix,
    invited_by_user_id, proposed_role_id, status, expires_at
)
VALUES (
    $1, $2, $3,
    $4, $5, $6,
    $7, $8, $9,
    $10, $11,
    $12, $13, $14, $15
)
RETURNING *;

-- name: GetInvitation :one
SELECT *
FROM invitation
WHERE id = $1;

-- name: GetInvitationByTokenHash :one
-- Constant-time-equality lookup. The plaintext token never touches the DB;
-- the caller computes sha256(token) and passes it as the argument.
SELECT *
FROM invitation
WHERE token_hash = $1;

-- name: ListInvitationsByOrganization :many
SELECT *
FROM invitation
WHERE organization_id = $1
ORDER BY created_at DESC, id DESC
LIMIT sqlc.arg('row_limit')::int;

-- name: MarkInvitationAccepted :one
UPDATE invitation
SET status = 'accepted',
    accepted_at = now(),
    accepted_by_user_id = sqlc.arg('accepted_by_user_id')
WHERE id = $1 AND status = 'pending'
RETURNING *;

-- name: MarkInvitationRevoked :one
UPDATE invitation
SET status = 'revoked',
    revoked_at = now(),
    revoked_by_user_id = sqlc.arg('revoked_by_user_id')
WHERE id = $1 AND row_seq = $2 AND status = 'pending'
RETURNING *;

-- name: ExpireOverdueInvitations :many
-- Sweeper helper. Flips every pending invitation past its expiry into
-- 'expired'. Returning the rows lets the sweeper emit one outbox event
-- per flipped row.
UPDATE invitation
SET status = 'expired'
WHERE status = 'pending'
  AND expires_at < sqlc.arg('now')::timestamptz
RETURNING id, tenant_id, organization_id;

-- name: CountActiveMembersByOrganization :one
SELECT COUNT(*) FROM member
WHERE organization_id = $1 AND status = 'active';
