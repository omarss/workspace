-- name: GetExternalUser :one
SELECT u.*
FROM external_users e
JOIN users u ON u.id = e.user_id
WHERE e.channel     = $1
  AND e.external_id = $2;

-- name: LinkExternalUser :exec
-- Idempotent. Conflict on (channel, external_id) bumps last_seen_at so we
-- have a cheap activity heartbeat.
INSERT INTO external_users (channel, external_id, user_id)
VALUES ($1, $2, $3)
ON CONFLICT (channel, external_id) DO UPDATE
SET last_seen_at = now();

-- name: CreateExternalUser :one
-- Used inside a transaction with LinkExternalUser when the (channel,
-- external_id) doesn't resolve. Nickname is intentionally empty — the bot
-- learns it later if the user volunteers one.
INSERT INTO users (nickname, email, phone)
VALUES ('', NULL, NULL)
RETURNING *;
