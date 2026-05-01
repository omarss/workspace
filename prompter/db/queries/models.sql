-- name: ListActiveModels :many
SELECT *
FROM models
WHERE active = true
ORDER BY param_count_b DESC;

-- name: GetModelBySlug :one
SELECT *
FROM models
WHERE slug = $1;

-- name: GetActiveModelBySlug :one
SELECT *
FROM models
WHERE slug = $1
  AND active = true;
