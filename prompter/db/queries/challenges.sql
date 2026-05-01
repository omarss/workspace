-- name: GetChallengeBySlug :one
SELECT *
FROM challenges
WHERE slug = $1;

-- name: GetChallengeByID :one
SELECT *
FROM challenges
WHERE id = $1;

-- name: GetActiveChallengeByID :one
-- "active" means within the active_from/active_to window. The window is
-- enforced here so handler code never has to think about it.
SELECT *
FROM challenges
WHERE id = $1
  AND active_from <= now()
  AND (active_to IS NULL OR active_to > now());

-- name: GetTodayDailyChallenge :one
-- Resolves the daily-mode challenge for today's date in UTC.
SELECT c.*
FROM daily_challenges d
JOIN challenges c ON c.id = d.challenge_id
WHERE d.challenge_date = (now() AT TIME ZONE 'UTC')::date;

-- name: ListPracticeChallenges :many
-- Practice mode: every active challenge for a modality, paged by recency.
SELECT *
FROM challenges
WHERE modality = $1
  AND active_from <= now()
  AND (active_to IS NULL OR active_to > now())
ORDER BY created_at DESC
LIMIT $2 OFFSET $3;
