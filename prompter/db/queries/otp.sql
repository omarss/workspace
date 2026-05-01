-- name: CreateEmailOTPChallenge :one
-- code_hash carries bcrypt(code); we own the secret on the email path.
INSERT INTO otp_challenges (channel, identifier, code_hash, expires_at, ip, ua)
VALUES ('email', $1, $2, $3, $4, $5)
RETURNING *;

-- name: CreateSMSOTPChallenge :one
-- provider_ref is the Twilio Verify SID; Twilio holds the secret on the SMS path.
INSERT INTO otp_challenges (channel, identifier, provider_ref, expires_at, ip, ua)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING *;

-- name: GetOTPChallengeByID :one
SELECT *
FROM otp_challenges
WHERE id = $1;

-- name: IncrementOTPAttempts :one
UPDATE otp_challenges
SET attempts = attempts + 1
WHERE id = $1
RETURNING *;

-- name: ConsumeOTPChallenge :exec
UPDATE otp_challenges
SET consumed_at = now()
WHERE id = $1
  AND consumed_at IS NULL;

-- name: CountRecentOTPChallengesForIdentifier :one
-- Used as a lightweight rate-limiter on the start path. The caller decides
-- the lookback window so the same query can serve "last minute" and
-- "last hour" buckets.
SELECT COUNT(*)::int
FROM otp_challenges
WHERE identifier = $1
  AND channel    = $2
  AND created_at > now() - $3::interval;
