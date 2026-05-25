-- name: CreateNotificationChannel :one
-- Inserts a new channel row. The repo layer runs the strict envelope walker
-- on the secrets payload before binding the parameters; this query is a thin
-- shim over a fully-formed row.
INSERT INTO notification_channel (
    id, tenant_id,
    provider, name, config,
    secrets_ciphertext, secrets_wrapped_dek, secrets_nonce, secrets_kid, secrets_key_version,
    is_default_for, status
)
VALUES (
    $1, $2,
    $3, $4, $5,
    $6, $7, $8, $9, $10,
    $11, $12
)
RETURNING *;

-- name: GetNotificationChannel :one
SELECT *
FROM notification_channel
WHERE id = $1 AND deleted_at IS NULL;

-- name: GetNotificationChannelByName :one
SELECT *
FROM notification_channel
WHERE tenant_id = $1 AND name = $2 AND deleted_at IS NULL;

-- name: ListNotificationChannels :many
SELECT *
FROM notification_channel
WHERE tenant_id = sqlc.arg('tenant_id')
  AND deleted_at IS NULL
ORDER BY created_at DESC, id DESC
LIMIT sqlc.arg('row_limit')::int;

-- name: UpdateNotificationChannelMeta :one
-- Metadata-only patch under optimistic concurrency. Does NOT accept new
-- credentials (per ADR 017 rotation is a distinct verb).
UPDATE notification_channel
SET
    name           = COALESCE(sqlc.narg('name'), name),
    status         = COALESCE(sqlc.narg('status'), status),
    is_default_for = COALESCE(sqlc.narg('is_default_for')::text[], is_default_for),
    config         = COALESCE(sqlc.narg('config'), config)
WHERE id = $1
  AND row_seq = $2
  AND deleted_at IS NULL
RETURNING *;

-- name: RotateNotificationChannelSecrets :one
-- Rotation endpoint: swaps the envelope columns and stamps last_rotated_at.
-- Bumps row_seq via the trigger.
UPDATE notification_channel
SET
    secrets_ciphertext  = sqlc.arg('secrets_ciphertext'),
    secrets_wrapped_dek = sqlc.arg('secrets_wrapped_dek'),
    secrets_nonce       = sqlc.arg('secrets_nonce'),
    secrets_kid         = sqlc.arg('secrets_kid'),
    secrets_key_version = sqlc.arg('secrets_key_version'),
    last_rotated_at     = now()
WHERE id = $1
  AND deleted_at IS NULL
RETURNING *;

-- name: SoftDeleteNotificationChannel :execrows
UPDATE notification_channel
SET status = 'disabled',
    deleted_at = now()
WHERE id = $1
  AND row_seq = $2
  AND deleted_at IS NULL;

-- name: SetNotificationChannelNovuIntegration :exec
UPDATE notification_channel
SET novu_integration_id = sqlc.arg('novu_integration_id')
WHERE id = $1
  AND deleted_at IS NULL;

-- name: RegisterNotificationWorkflow :one
INSERT INTO notification_workflow (id, tenant_id, name, novu_workflow_id, description)
VALUES ($1, $2, $3, $4, $5)
RETURNING *;

-- name: GetNotificationWorkflow :one
SELECT *
FROM notification_workflow
WHERE id = $1;

-- name: GetNotificationWorkflowByName :one
SELECT *
FROM notification_workflow
WHERE tenant_id = $1 AND name = $2;

-- name: ListNotificationWorkflows :many
SELECT *
FROM notification_workflow
WHERE tenant_id = $1
ORDER BY created_at DESC, id DESC;

-- name: UpdateNotificationWorkflow :one
-- COALESCE keeps each column unchanged when the caller passes NULL. The
-- description column accepts an explicit NULL only by clearing the patch
-- field at the service layer; the wire-level patch model carries a flag.
UPDATE notification_workflow
SET
    novu_workflow_id = COALESCE(sqlc.narg('novu_workflow_id'), novu_workflow_id),
    description      = COALESCE(sqlc.narg('description'), description)
WHERE id = $1 AND tenant_id = sqlc.arg('tenant_id')
RETURNING *;

-- name: CreateNotification :one
INSERT INTO notification (
    id, tenant_id, workflow_name, to_user_id,
    payload_ciphertext, payload_wrapped_dek, payload_nonce, payload_kid, payload_key_version,
    status
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
RETURNING *;

-- name: GetNotification :one
SELECT *
FROM notification
WHERE id = $1;

-- name: ListNotifications :many
SELECT *
FROM notification
WHERE tenant_id = sqlc.arg('tenant_id')
  AND (
      sqlc.narg('cursor_queued_at')::timestamptz IS NULL
      OR (queued_at, id) < (sqlc.narg('cursor_queued_at')::timestamptz, sqlc.narg('cursor_id')::text)
  )
ORDER BY queued_at DESC, id DESC
LIMIT sqlc.arg('row_limit')::int;

-- name: UpdateNotificationStatus :one
UPDATE notification
SET status         = sqlc.arg('status'),
    sent_at        = CASE WHEN sqlc.arg('status') = 'sent'      THEN now() ELSE sent_at      END,
    delivered_at   = CASE WHEN sqlc.arg('status') = 'delivered' THEN now() ELSE delivered_at END,
    failed_at      = CASE WHEN sqlc.arg('status') = 'failed'    THEN now() ELSE failed_at    END,
    failure_reason = sqlc.narg('failure_reason'),
    novu_transaction_id = COALESCE(sqlc.narg('novu_transaction_id'), novu_transaction_id)
WHERE id = $1
RETURNING *;

-- name: InsertNotificationAttempt :exec
INSERT INTO notification_attempt (notification_id, status, failure_reason)
VALUES ($1, $2, $3);
