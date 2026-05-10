-- name: SetLeaderboardOptIn :exec
UPDATE users
SET leaderboard_opt_in = $2,
    updated_at         = now()
WHERE id = $1;

-- name: SetUserNickname :exec
UPDATE users
SET nickname   = $2,
    updated_at = now()
WHERE id = $1;

-- name: MasteryLeaderboard :many
-- Top users by accuracy. Restricted to opt-in users with at least
-- min_attempts answered (spec §22 rule 8: don't rank tiny samples).
-- Phone is never selected; nickname is the only public identifier.
SELECT u.id,
       (COALESCE(NULLIF(u.nickname, ''), 'بدون اسم'))::text   AS nickname,
       COUNT(*)::int                                  AS attempts,
       AVG(CASE WHEN a.correct THEN 1.0 ELSE 0.0 END) AS accuracy
FROM users    u
JOIN attempts a ON a.user_id = u.id
JOIN items    i ON i.id      = a.item_id
WHERE u.leaderboard_opt_in = true
  AND a.correct IS NOT NULL
  AND (sqlc.narg('exam_type')::text IS NULL OR i.exam_type = sqlc.narg('exam_type'))
GROUP BY u.id, u.nickname
HAVING COUNT(*) >= sqlc.arg('min_attempts')::int
ORDER BY accuracy DESC, attempts DESC
LIMIT sqlc.arg('limit_count');

-- name: ImprovementLeaderboard :many
-- Week-over-week accuracy delta. Rewards growth, not raw skill — the
-- safe-leaderboard goal from spec §22 rule 5. min_attempts gates noisy
-- readings from very small samples.
SELECT u.id,
       (COALESCE(NULLIF(u.nickname, ''), 'بدون اسم'))::text AS nickname,
       SUM(CASE WHEN a.answered_at >= date_trunc('week', now()) THEN 1 ELSE 0 END)::int
                                                    AS attempts_this_week,
       AVG(CASE WHEN a.answered_at >= date_trunc('week', now()) AND a.correct THEN 1.0
                WHEN a.answered_at >= date_trunc('week', now())                 THEN 0.0
                ELSE NULL END)::float8              AS this_week_accuracy,
       AVG(CASE WHEN a.answered_at >= date_trunc('week', now()) - interval '7 days'
                 AND a.answered_at <  date_trunc('week', now())
                 AND a.correct THEN 1.0
                WHEN a.answered_at >= date_trunc('week', now()) - interval '7 days'
                 AND a.answered_at <  date_trunc('week', now())
                THEN 0.0
                ELSE NULL END)::float8              AS last_week_accuracy
FROM users    u
JOIN attempts a ON a.user_id = u.id
WHERE u.leaderboard_opt_in = true
  AND a.correct IS NOT NULL
  AND a.answered_at >= date_trunc('week', now()) - interval '7 days'
GROUP BY u.id, u.nickname
HAVING SUM(CASE WHEN a.answered_at >= date_trunc('week', now()) THEN 1 ELSE 0 END) >= sqlc.arg('min_attempts')::int
ORDER BY (
    AVG(CASE WHEN a.answered_at >= date_trunc('week', now()) AND a.correct THEN 1.0
             WHEN a.answered_at >= date_trunc('week', now())                 THEN 0.0
             ELSE NULL END)
  - COALESCE(AVG(CASE WHEN a.answered_at >= date_trunc('week', now()) - interval '7 days'
                       AND a.answered_at <  date_trunc('week', now())
                       AND a.correct THEN 1.0
                      WHEN a.answered_at >= date_trunc('week', now()) - interval '7 days'
                       AND a.answered_at <  date_trunc('week', now())
                      THEN 0.0
                      ELSE NULL END), 0)
) DESC NULLS LAST
LIMIT sqlc.arg('limit_count');
