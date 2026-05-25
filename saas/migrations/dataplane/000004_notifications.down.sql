-- Forward-only schema policy applies (CONVENTIONS.md §4). This down file
-- exists for local dev rollbacks only — production never runs migrate down.

DROP TABLE IF EXISTS notification_attempt;
DROP TABLE IF EXISTS notification;
DROP TABLE IF EXISTS notification_workflow;
DROP TABLE IF EXISTS notification_channel;
