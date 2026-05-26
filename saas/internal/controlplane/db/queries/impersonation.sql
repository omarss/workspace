-- Impersonation session lifecycle queries.
--
-- The impersonation service.go (Phase 13) drives this table through
-- four operations:
--
--   - Insert  — at session start, BEFORE the JWT is signed so a token
--     never escapes without an audit row.
--   - Get     — to surface the row to the operator (end / inspect).
--   - IsActive — fast existence check used by the data-plane auth
--     middleware on every request that carries an impersonation JWT.
--   - End     — sets ended_at + ended_reason. The append-only trigger
--     on impersonation_session refuses changes to any other column.

-- name: InsertImpersonationSession :exec
INSERT INTO impersonation_session (
    id,
    deployment_id,
    operator_id,
    operator_email,
    target_member_id,
    target_tenant_id,
    reason,
    duration_seconds,
    issued_at,
    expires_at
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10);

-- name: GetImpersonationSession :one
SELECT * FROM impersonation_session WHERE id = $1;

-- name: IsImpersonationSessionActive :one
-- Active = exists, not yet ended, not yet expired. The middleware
-- consults this on every request so we keep the predicate index-friendly
-- (matches the partial index impersonation_session_active_idx).
SELECT EXISTS (
    SELECT 1
    FROM impersonation_session
    WHERE id = $1
      AND ended_at IS NULL
      AND expires_at > now()
) AS active;

-- name: EndImpersonationSession :exec
-- Idempotent: only writes ended_at when the row is still active. The
-- trigger forbids touching any column other than ended_at and
-- ended_reason, so this projection is the only legal UPDATE shape.
UPDATE impersonation_session
SET ended_at     = now(),
    ended_reason = sqlc.narg('ended_reason')
WHERE id = sqlc.arg('id')
  AND ended_at IS NULL;
