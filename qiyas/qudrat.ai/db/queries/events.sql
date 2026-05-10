-- name: RecordEvent :exec
INSERT INTO events (event_type, user_id, item_id, payload)
VALUES ($1, $2, $3, COALESCE($4::jsonb, '{}'::jsonb));

-- name: CountEventsByTypeSince :one
SELECT COUNT(*)::int
FROM events
WHERE event_type = $1
  AND created_at >= $2;

-- name: ListRecentEventsByType :many
SELECT id, event_type, user_id, item_id, payload, created_at
FROM events
WHERE event_type = $1
ORDER BY created_at DESC
LIMIT $2;
