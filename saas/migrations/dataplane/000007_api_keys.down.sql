-- Forward-only schema policy applies (CONVENTIONS.md §4). This down file
-- exists for local dev rollbacks only — production never runs migrate
-- down. We drop the table; the permission rows live in the catalogue
-- table from Phase 8 and are left in place (no other module depends on
-- their absence).

DROP TABLE IF EXISTS api_key;
