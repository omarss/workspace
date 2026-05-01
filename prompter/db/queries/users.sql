-- name: CreateUser :one
INSERT INTO users (email, phone, display_name)
VALUES ($1, $2, $3)
RETURNING *;

-- name: GetUserByEmail :one
SELECT *
FROM users
WHERE email = $1;

-- name: GetUserByPhone :one
SELECT *
FROM users
WHERE phone = $1;

-- name: GetUserByID :one
SELECT *
FROM users
WHERE id = $1;

-- name: TouchUserLastLogin :exec
UPDATE users
SET last_login_at = now()
WHERE id = $1;
