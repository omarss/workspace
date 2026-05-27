-- Operator inventory read-side queries.
--
-- The Phase 13 ipallowlist + step-up middleware and the saasctl
-- operator subtree both look operators up by id (JWT subject) or by
-- keycloak_user_id (when the realm-linked path is used). These three
-- queries are the only read paths exposed today; write paths (add /
-- remove / update-allowlist) land alongside the gocloak admin client.
--
-- All three projections return the same column set so the Querier
-- interface in internal/controlplane/operatorrepo/ stays small and the
-- saasctl operator list / inspect commands can share rendering code.

-- name: GetOperatorByID :one
SELECT
    id,
    keycloak_user_id,
    email,
    name,
    is_active,
    mfa_enabled,
    mfa_required,
    amr,
    last_step_up_at,
    ip_allowlist
FROM operator
WHERE id = $1;

-- name: GetOperatorByKeycloakUserID :one
SELECT
    id,
    keycloak_user_id,
    email,
    name,
    is_active,
    mfa_enabled,
    mfa_required,
    amr,
    last_step_up_at,
    ip_allowlist
FROM operator
WHERE keycloak_user_id = sqlc.narg('keycloak_user_id');

-- name: ListActiveOperators :many
SELECT
    id,
    keycloak_user_id,
    email,
    name,
    is_active,
    mfa_enabled,
    mfa_required,
    amr,
    last_step_up_at,
    ip_allowlist
FROM operator
WHERE is_active = true
ORDER BY id ASC;
