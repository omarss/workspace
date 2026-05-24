-- name: InsertOutboxEvent :one
INSERT INTO outbox_event (event_id, type, event_version, tenant_id, deployment_id, payload)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id, event_id, type, event_version, tenant_id, deployment_id, occurred_at, payload, published_at, delivery_attempts, last_error;

-- name: ListUnpublishedOutbox :many
SELECT id, event_id, type, event_version, tenant_id, deployment_id, occurred_at, payload, published_at, delivery_attempts, last_error
FROM outbox_event
WHERE published_at IS NULL
ORDER BY id
LIMIT $1;

-- name: MarkOutboxPublished :exec
UPDATE outbox_event SET published_at = now() WHERE id = $1;

-- name: MarkOutboxFailed :exec
UPDATE outbox_event
SET delivery_attempts = delivery_attempts + 1,
    last_error        = $2
WHERE id = $1;
