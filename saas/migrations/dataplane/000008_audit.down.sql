-- Forward-only schema policy applies (CONVENTIONS.md §4). This down file
-- exists for local dev rollbacks only — production never runs migrate
-- down. We drop the table; the permission row (`perm_audit_read`) is
-- left in the catalogue because v1 RBAC may resurrect it. Re-creating
-- the table by running the .up.sql again is idempotent against the
-- catalogue thanks to the ON CONFLICT clause.

DROP TRIGGER IF EXISTS audit_event_no_update_trg ON audit_event;
DROP TRIGGER IF EXISTS audit_event_no_delete_trg ON audit_event;
DROP FUNCTION IF EXISTS audit_event_no_update();
DROP FUNCTION IF EXISTS audit_event_no_delete();
DROP TABLE IF EXISTS audit_event;
