-- name: CreatePlatformUser :one
-- Inserts a fully-formed envelope row. The caller (PgxRepository) computes
-- email_lookup_hash and runs the persistence walker to populate the
-- envelope columns before binding the parameters.
INSERT INTO platform_user (
    id, tenant_id,
    email_lookup_hash, email_ciphertext, email_wrapped_dek, email_nonce, email_kid, email_key_version, email_verified,
    name_ciphertext, name_wrapped_dek, name_nonce, name_kid, name_key_version,
    phone_ciphertext, phone_wrapped_dek, phone_nonce, phone_kid, phone_key_version,
    keycloak_user_id, status, metadata
)
VALUES (
    $1, $2,
    $3, $4, $5, $6, $7, $8, $9,
    $10, $11, $12, $13, $14,
    $15, $16, $17, $18, $19,
    $20, $21, $22
)
RETURNING *;

-- name: GetPlatformUser :one
SELECT *
FROM platform_user
WHERE id = $1 AND deleted_at IS NULL;

-- name: GetPlatformUserByEmailHash :one
SELECT *
FROM platform_user
WHERE tenant_id = $1 AND email_lookup_hash = $2 AND deleted_at IS NULL;

-- name: GetPlatformUserByKeycloakID :one
SELECT *
FROM platform_user
WHERE keycloak_user_id = $1 AND deleted_at IS NULL;

-- name: ListPlatformUsers :many
-- Keyset pagination on (created_at DESC, id DESC). row_limit is limit+1 so
-- the caller can detect has_more.
SELECT *
FROM platform_user
WHERE tenant_id = sqlc.arg('tenant_id')
  AND deleted_at IS NULL
  AND (
    sqlc.narg('cursor_created_at')::timestamptz IS NULL
    OR (created_at, id) < (sqlc.narg('cursor_created_at')::timestamptz, sqlc.narg('cursor_id')::text)
  )
ORDER BY created_at DESC, id DESC
LIMIT sqlc.arg('row_limit')::int;

-- name: UpdatePlatformUser :one
-- Patch name/phone envelope columns + metadata under optimistic concurrency.
-- Each PII field updates the full five-column envelope set; the caller passes
-- nil when the column should not change.
UPDATE platform_user
SET
    name_ciphertext   = COALESCE(sqlc.narg('name_ciphertext'),   name_ciphertext),
    name_wrapped_dek  = COALESCE(sqlc.narg('name_wrapped_dek'),  name_wrapped_dek),
    name_nonce        = COALESCE(sqlc.narg('name_nonce'),        name_nonce),
    name_kid          = COALESCE(sqlc.narg('name_kid'),          name_kid),
    name_key_version  = COALESCE(sqlc.narg('name_key_version'),  name_key_version),
    phone_ciphertext  = COALESCE(sqlc.narg('phone_ciphertext'),  phone_ciphertext),
    phone_wrapped_dek = COALESCE(sqlc.narg('phone_wrapped_dek'), phone_wrapped_dek),
    phone_nonce       = COALESCE(sqlc.narg('phone_nonce'),       phone_nonce),
    phone_kid         = COALESCE(sqlc.narg('phone_kid'),         phone_kid),
    phone_key_version = COALESCE(sqlc.narg('phone_key_version'), phone_key_version),
    metadata          = COALESCE(sqlc.narg('metadata'),          metadata)
WHERE id = $1
  AND row_seq = $2
  AND deleted_at IS NULL
RETURNING *;

-- name: SetPlatformUserStatus :one
-- Disable/enable transitions go through here so the row_seq trigger fires
-- and outbox subscribers see the change. Cannot transition out of 'deleted'.
UPDATE platform_user
SET status = sqlc.arg('status')
WHERE id = $1
  AND deleted_at IS NULL
  AND status != 'deleted'
RETURNING *;

-- name: SetPlatformUserEmailVerified :one
UPDATE platform_user
SET email_verified = sqlc.arg('email_verified')
WHERE id = $1 AND deleted_at IS NULL
RETURNING *;

-- name: SoftDeletePlatformUser :one
UPDATE platform_user
SET status     = 'deleted',
    deleted_at = now()
WHERE id = $1
  AND row_seq = $2
  AND deleted_at IS NULL
RETURNING *;

-- name: LinkIdentityProvider :exec
INSERT INTO identity_provider_mapping (platform_user_id, tenant_id, provider, external_subject)
VALUES ($1, $2, $3, $4)
ON CONFLICT (platform_user_id, provider) DO UPDATE
    SET external_subject = EXCLUDED.external_subject,
        linked_at        = now();

-- name: UnlinkIdentityProvider :execrows
DELETE FROM identity_provider_mapping
WHERE platform_user_id = $1 AND provider = $2;

-- name: ListIdentityProviders :many
SELECT provider, external_subject, linked_at
FROM identity_provider_mapping
WHERE platform_user_id = $1 AND tenant_id = $2
ORDER BY linked_at DESC;

-- name: InsertSocialLoginState :exec
INSERT INTO social_login_state (state, tenant_id, platform_user_id, provider, return_to, nonce, expires_at)
VALUES ($1, $2, $3, $4, $5, $6, $7);

-- name: ConsumeSocialLoginState :one
-- Atomically marks the row consumed and returns it. Returns no rows if the
-- state is already consumed or expired — the caller surfaces this as a 400
-- "state-already-used" or "state-expired" problem.
UPDATE social_login_state
SET consumed_at = now()
WHERE state = $1
  AND consumed_at IS NULL
  AND expires_at > now()
RETURNING *;

-- name: DeleteExpiredSocialLoginStates :execrows
DELETE FROM social_login_state
WHERE expires_at < now() - interval '1 hour';
