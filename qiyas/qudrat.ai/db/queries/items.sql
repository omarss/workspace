-- name: InsertItem :one
INSERT INTO items (
    status, exam_type, section, subject, grade_level, unit, topic, skill,
    cognitive_level, difficulty_target, question_archetype,
    question_text, correct_answer, explanation, estimated_time_seconds,
    concept_fingerprint, solution_fingerprint, surface_fingerprint,
    normalized_text_hash, stem_hash, choices_hash,
    source, model_name, generation_prompt_version, review_prompt_version,
    novelty_notes
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8,
    $9, $10, $11,
    $12, $13, $14, $15,
    $16, $17, $18,
    $19, $20, $21,
    $22, $23, $24, $25,
    $26
)
RETURNING *;

-- name: InsertItemChoice :exec
INSERT INTO item_choices (item_id, choice_key, choice_text, distractor_rationale)
VALUES ($1, $2, $3, $4);

-- name: InsertItemTag :exec
INSERT INTO item_tags (item_id, tag)
VALUES ($1, $2)
ON CONFLICT DO NOTHING;

-- name: GetItemByNormalizedHash :one
SELECT *
FROM items
WHERE normalized_text_hash = $1;

-- name: CountItems :one
SELECT count(*) FROM items;

-- name: CountAcceptedItems :one
SELECT count(*) FROM items WHERE status = 'accepted';

-- name: ListItemsByTopic :many
SELECT *
FROM items
WHERE status = 'accepted'
  AND exam_type = $1
  AND topic     = $2
ORDER BY created_at DESC
LIMIT $3 OFFSET $4;

-- name: GetItemByID :one
SELECT *
FROM items
WHERE id = $1;

-- name: ListItemChoices :many
SELECT *
FROM item_choices
WHERE item_id = $1
ORDER BY choice_key;

-- name: ListItemTags :many
SELECT tag
FROM item_tags
WHERE item_id = $1
ORDER BY tag;
