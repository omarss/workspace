-- name: CreateTrialSubscription :one
INSERT INTO subscriptions (user_id, plan, status)
VALUES ($1, 'free', 'trial')
RETURNING *;

-- name: GetCurrentSubscription :one
-- Most recent active row for the user. Returns no rows if the user has
-- never been issued a subscription (trial or otherwise).
SELECT *
FROM subscriptions
WHERE user_id = $1
  AND status IN ('trial', 'active', 'past_due')
ORDER BY started_at DESC
LIMIT 1;

-- name: ActivatePaidSubscription :exec
-- Used by the webhook handler when a payment lands. The webhook plumbing
-- is out of Phase 9 scope but the persistence side is here so subsequent
-- phases can flip status without a migration.
UPDATE subscriptions
SET status        = 'active',
    plan          = $2,
    provider      = $3,
    provider_ref  = $4,
    renewed_at    = now(),
    expires_at    = $5,
    updated_at    = now()
WHERE id = $1;

-- name: CancelSubscription :exec
UPDATE subscriptions
SET status       = 'cancelled',
    cancelled_at = now(),
    updated_at   = now()
WHERE id = $1
  AND status IN ('trial', 'active', 'past_due');

-- name: CountAttemptsToday :one
-- Used by the trial-quota gate. answered_at is the timestamp the user
-- actually committed an answer; only counted answers consume quota.
SELECT COUNT(*)::int
FROM attempts
WHERE user_id     = $1
  AND answered_at >= date_trunc('day', now())
  AND choice_key  IS NOT NULL;
