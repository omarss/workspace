-- Down migration is allowed but optional (forward-only policy in AGENTS.md
-- section 25.4). Safe only when no production data exists; CI uses a clean
-- ephemeral DB so the drop is benign there.
DROP TABLE IF EXISTS idempotency_record CASCADE;
DROP TABLE IF EXISTS outbox_event       CASCADE;
DROP TRIGGER IF EXISTS tenant_bump_row_seq ON tenant;
DROP FUNCTION IF EXISTS bump_row_seq();
DROP TABLE IF EXISTS tenant CASCADE;
