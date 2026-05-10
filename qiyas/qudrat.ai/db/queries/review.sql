-- name: GetItemByConceptSolutionFingerprint :one
-- Near-dup detector: returns the first accepted item that matches BOTH
-- concept_fingerprint AND solution_fingerprint. Empty fingerprints don't
-- count (they're the placeholder in items not authored by the new pipeline).
SELECT *
FROM items
WHERE status               = 'accepted'
  AND concept_fingerprint  = $1
  AND solution_fingerprint = $2
  AND concept_fingerprint  <> ''
  AND solution_fingerprint <> ''
LIMIT 1;

-- name: ListItemsNeedingReview :many
SELECT i.id, i.exam_type, i.section, i.subject, i.topic, i.skill,
       i.difficulty_target, i.question_archetype, i.question_text,
       i.concept_fingerprint, i.solution_fingerprint, i.surface_fingerprint,
       i.created_at
FROM items i
WHERE i.status = 'needs_review'
ORDER BY i.created_at DESC
LIMIT $1 OFFSET $2;

-- name: CountItemsNeedingReview :one
SELECT COUNT(*)::int FROM items WHERE status = 'needs_review';

-- name: SetItemStatus :exec
UPDATE items
SET status     = $2,
    updated_at = now()
WHERE id = $1;

-- name: SetItemQualityScore :exec
-- Used by the reviewer-LLM pass once it lands (Phase 7 stub for now).
UPDATE items
SET quality_score      = $2,
    novelty_score      = $3,
    ambiguity_score    = $4,
    review_prompt_version = $5,
    updated_at         = now()
WHERE id = $1;
