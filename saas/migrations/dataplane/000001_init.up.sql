-- placeholder; real schema lands in Phase 2.
CREATE TABLE IF NOT EXISTS schema_bootstrap_dataplane (
    bootstrapped_at timestamptz NOT NULL DEFAULT now()
);
