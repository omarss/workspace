-- name: CreateSubmission :one
INSERT INTO submissions (
    user_id, challenge_id, model_slug, prompt, prompt_tokens, status, seed
) VALUES ($1, $2, $3, $4, $5, 'queued', $6)
RETURNING *;

-- name: RejectSubmission :one
INSERT INTO submissions (
    user_id, challenge_id, model_slug, prompt, prompt_tokens, status, reject_reason, seed
) VALUES ($1, $2, $3, $4, $5, 'rejected', $6, $7)
RETURNING *;

-- name: GetSubmissionByIDForUser :one
SELECT *
FROM submissions
WHERE id = $1
  AND user_id = $2;

-- name: ListUserSubmissions :many
SELECT *
FROM submissions
WHERE user_id = $1
ORDER BY created_at DESC
LIMIT $2 OFFSET $3;

-- name: PickAndLockQueuedSubmission :one
-- Worker poll path. SKIP LOCKED makes multiple workers safe.
UPDATE submissions
SET status = 'running'
WHERE id = (
    SELECT id FROM submissions
    WHERE status = 'queued'
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING *;

-- name: MarkSubmissionGraded :one
UPDATE submissions
SET status        = 'graded',
    output_code   = $2,
    similarity    = $3,
    tests_passed  = $4,
    tests_total   = $5,
    multiplier    = $6,
    brevity       = $7,
    score         = $8,
    graded_at     = now()
WHERE id = $1
RETURNING *;

-- name: MarkSubmissionFailed :one
UPDATE submissions
SET status        = 'rejected',
    reject_reason = $2,
    graded_at     = now()
WHERE id = $1
RETURNING *;
