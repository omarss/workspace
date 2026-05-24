-- name: ClaimIdempotencyRecord :one
-- Insert-or-no-op claim. Returns the new row if the key is fresh; returns no
-- rows when another concurrent request already claimed the slot (handler then
-- calls GetIdempotencyRecord to fetch the cached state).
INSERT INTO idempotency_record
    (tenant_id, idempotency_key, route, method, request_body_hash, expires_at)
VALUES ($1, $2, $3, $4, $5, now() + interval '24 hours')
ON CONFLICT (tenant_id, idempotency_key, route, method) DO NOTHING
RETURNING id, tenant_id, idempotency_key, route, method, request_body_hash, response_status, response_headers, response_body, in_flight, created_at, expires_at;

-- name: GetIdempotencyRecord :one
SELECT id, tenant_id, idempotency_key, route, method, request_body_hash, response_status, response_headers, response_body, in_flight, created_at, expires_at
FROM idempotency_record
WHERE tenant_id = $1 AND idempotency_key = $2 AND route = $3 AND method = $4;

-- name: FinishIdempotencyRecord :exec
UPDATE idempotency_record
SET response_status  = $2,
    response_headers = $3,
    response_body    = $4,
    in_flight        = false
WHERE id = $1;

-- name: ExpireIdempotencyRecords :exec
DELETE FROM idempotency_record WHERE expires_at < now();
