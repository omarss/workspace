-- name: RequestParentLink :one
-- Parent kicks off the link by referencing the child's identifier
-- (email/phone). The child still has to accept via /parent/links/{id}/accept.
INSERT INTO parent_links (parent_id, child_id, status)
VALUES ($1, $2, 'pending')
ON CONFLICT (parent_id, child_id) DO UPDATE
SET status     = CASE WHEN parent_links.status = 'revoked' THEN 'pending' ELSE parent_links.status END,
    created_at = CASE WHEN parent_links.status = 'revoked' THEN now()      ELSE parent_links.created_at END
RETURNING *;

-- name: AcceptParentLink :exec
UPDATE parent_links
SET status      = 'accepted',
    accepted_at = now()
WHERE id        = $1
  AND child_id  = $2
  AND status    = 'pending';

-- name: RevokeParentLink :exec
UPDATE parent_links
SET status     = 'revoked',
    revoked_at = now()
WHERE id        = $1
  AND (parent_id = $2 OR child_id = $2);

-- name: ListChildrenForParent :many
SELECT pl.id, pl.child_id, pl.status, pl.created_at, pl.accepted_at,
       u.nickname AS child_nickname
FROM parent_links pl
JOIN users u ON u.id = pl.child_id
WHERE pl.parent_id = $1
ORDER BY pl.created_at DESC;

-- name: GetParentLinkForView :one
-- Lookup that confirms a parent has consent to view a child's summary.
SELECT *
FROM parent_links
WHERE parent_id = $1
  AND child_id  = $2
  AND status    = 'accepted'
LIMIT 1;

-- name: WeeklySummaryForUser :one
-- Aggregated read for the parent dashboard. Counts attempts in the last
-- 7 days, average accuracy, and number of distinct days with activity
-- (proxy for consistency).
SELECT COUNT(*)::int                                          AS attempts,
       COALESCE(AVG(CASE WHEN correct THEN 1.0 ELSE 0.0 END), 0)::float8 AS accuracy,
       COUNT(DISTINCT date_trunc('day', served_at))::int      AS active_days
FROM attempts
WHERE user_id     = $1
  AND served_at  >= now() - interval '7 days'
  AND choice_key IS NOT NULL;
