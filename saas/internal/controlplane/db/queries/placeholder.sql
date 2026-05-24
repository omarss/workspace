-- Placeholder. Real control-plane queries land in Phase 11 (control plane
-- skeleton). sqlc rejects empty query directories so this stub satisfies the
-- generator without emitting any Go.

-- name: GetControlPlaneBootstrap :one
SELECT bootstrapped_at FROM schema_bootstrap_controlplane LIMIT 1;
