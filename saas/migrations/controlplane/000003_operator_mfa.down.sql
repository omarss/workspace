-- Phase 13 — rollback for operator MFA / step-up / impersonation tables.
--
-- Forward-only is the project rule (CLAUDE.md §5), but the down migration
-- lives next to the up so a developer's local Postgres can be reset
-- between local schema iterations. Production migrations never invoke
-- this — the schema column drops would lose audit history.

DROP TRIGGER IF EXISTS impersonation_session_no_destructive_update ON impersonation_session;
DROP TRIGGER IF EXISTS impersonation_session_no_delete             ON impersonation_session;
DROP FUNCTION IF EXISTS impersonation_session_immutable();

DROP INDEX IF EXISTS impersonation_session_active_idx;
DROP INDEX IF EXISTS impersonation_session_dep_idx;
DROP INDEX IF EXISTS impersonation_session_op_idx;
DROP TABLE IF EXISTS impersonation_session;

DROP INDEX IF EXISTS operator_email_idx;

ALTER TABLE operator
    DROP COLUMN IF EXISTS mfa_required,
    DROP COLUMN IF EXISTS last_step_up_at,
    DROP COLUMN IF EXISTS amr,
    DROP COLUMN IF EXISTS name,
    DROP COLUMN IF EXISTS email,
    DROP COLUMN IF EXISTS keycloak_user_id;
