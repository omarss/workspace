-- Forward-only schema policy applies (CONVENTIONS.md §4). This down file
-- exists for local dev rollbacks only — production never runs migrate down.

ALTER TABLE member DROP CONSTRAINT IF EXISTS member_role_id_fkey;
DROP INDEX IF EXISTS member_role_id_idx;

DROP TABLE IF EXISTS member_role;
DROP TABLE IF EXISTS permission;
DROP TABLE IF EXISTS role;
DROP TABLE IF EXISTS casbin_rule;
