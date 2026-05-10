-- name: ItemsToCalibrate :many
-- Items with at least min_attempts answered. Calibration computes a
-- per-item accuracy and stores it in items.difficulty_calibrated.
SELECT i.id,
       COUNT(*)::int                                  AS attempts,
       AVG(CASE WHEN a.correct THEN 1.0 ELSE 0.0 END) AS accuracy
FROM items    i
JOIN attempts a ON a.item_id = i.id
WHERE a.correct IS NOT NULL
GROUP BY i.id
HAVING COUNT(*) >= sqlc.arg('min_attempts')::int;

-- name: UpdateItemCalibratedDifficulty :exec
UPDATE items
SET difficulty_calibrated = $2,
    updated_at            = now()
WHERE id = $1;
