-- name: CreateSession :one
INSERT INTO sessions (user_id, refresh_hash, expires_at, ip, ua)
VALUES ($1, $2, $3, $4, $5)
RETURNING *;

-- name: GetActiveSessionByRefreshHash :one
SELECT *
FROM sessions
WHERE refresh_hash = $1
  AND revoked_at   IS NULL
  AND expires_at   > now();

-- name: TouchSessionLastSeen :exec
UPDATE sessions
SET last_seen_at = now()
WHERE id = $1;

-- name: RevokeSession :exec
UPDATE sessions
SET revoked_at = now()
WHERE id = $1
  AND revoked_at IS NULL;

-- name: RevokeAllUserSessions :exec
UPDATE sessions
SET revoked_at = now()
WHERE user_id = $1
  AND revoked_at IS NULL;
