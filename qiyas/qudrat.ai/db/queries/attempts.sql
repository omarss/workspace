-- name: PickUnservedItemsForUser :many
-- Returns up to limit_count accepted items the user has never been served.
-- Filters by exam_type/section/topic if provided (NULL = no filter).
-- Random ordering keeps practice fresh; for ~10k items the cost is fine.
SELECT i.id, i.exam_type, i.section, i.subject, i.grade_level, i.unit, i.topic,
       i.skill, i.cognitive_level, i.difficulty_target, i.question_archetype,
       i.question_text, i.estimated_time_seconds
FROM items i
WHERE i.status = 'accepted'
  AND (sqlc.narg('exam_type')::text IS NULL OR i.exam_type = sqlc.narg('exam_type'))
  AND (sqlc.narg('section')::text   IS NULL OR i.section   = sqlc.narg('section'))
  AND (sqlc.narg('topic')::text     IS NULL OR i.topic     = sqlc.narg('topic'))
  AND NOT EXISTS (
      SELECT 1 FROM served_items s
      WHERE s.user_id = sqlc.arg('user_id')
        AND s.item_id = i.id
  )
ORDER BY random()
LIMIT sqlc.arg('limit_count');

-- name: MarkItemServed :exec
-- Idempotent: ON CONFLICT DO NOTHING means re-serving (e.g. retry after a
-- network error) doesn't fail. The PRIMARY KEY (user_id,item_id) covers it.
INSERT INTO served_items (user_id, item_id)
VALUES ($1, $2)
ON CONFLICT (user_id, item_id) DO NOTHING;

-- name: GetItemForAttempt :one
-- Returns the full item row including correct_answer + explanation. Callers
-- compare the user's choice to correct_answer in code rather than at the SQL
-- layer so they can return the same row to the client (with the answer + why
-- each distractor was wrong). The item must be accepted.
SELECT *
FROM items
WHERE id = $1
  AND status = 'accepted';

-- name: ListItemChoicesByID :many
-- Same contract as ListItemChoices but with explicit name to avoid collision.
SELECT *
FROM item_choices
WHERE item_id = $1
ORDER BY choice_key;

-- name: InsertAttempt :one
-- One row per answered item per user. choice_key + correct are nullable to
-- support a "served but skipped" path later (Phase 4 mistake-clinic).
INSERT INTO attempts (user_id, item_id, choice_key, correct, time_taken_ms, hint_used, served_at, answered_at)
VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7::timestamptz, now()), now())
RETURNING *;

-- name: ListRecentAttemptsForUser :many
SELECT a.*, i.exam_type, i.section, i.topic, i.skill, i.difficulty_target
FROM attempts a
JOIN items   i ON i.id = a.item_id
WHERE a.user_id = $1
ORDER BY a.served_at DESC
LIMIT $2;

-- name: CountAttemptsForUser :one
SELECT COUNT(*)::int FROM attempts WHERE user_id = $1;

-- name: SummarizeMasteryByTopic :many
-- Per-topic accuracy + counts for the user. Drives the weakness heatmap
-- (spec §4 #8). LIMIT keeps the payload bounded.
SELECT i.exam_type,
       i.section,
       i.topic,
       COUNT(*)::int                                     AS attempts,
       SUM(CASE WHEN a.correct THEN 1 ELSE 0 END)::int   AS correct_count,
       AVG(CASE WHEN a.correct THEN 1.0 ELSE 0.0 END)    AS accuracy
FROM attempts a
JOIN items   i ON i.id = a.item_id
WHERE a.user_id = $1
  AND a.choice_key IS NOT NULL
GROUP BY i.exam_type, i.section, i.topic
ORDER BY accuracy ASC
LIMIT $2;
