-- placeholder; real schema lands in Phase 10.
CREATE TABLE IF NOT EXISTS schema_bootstrap_controlplane (
    bootstrapped_at timestamptz NOT NULL DEFAULT now()
);
