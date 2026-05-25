-- Forward-only schema policy applies (CONVENTIONS.md §4). This down file
-- exists for local dev rollbacks only — production never runs migrate down.

DROP TABLE IF EXISTS invitation;
DROP TABLE IF EXISTS member;
DROP TABLE IF EXISTS organization;
