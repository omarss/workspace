-- Forward-only schema policy applies (CONVENTIONS.md §4). This down file
-- exists for local dev rollbacks only — production never runs migrate down.

DROP TABLE IF EXISTS social_login_state;
DROP TABLE IF EXISTS identity_provider_mapping;
DROP TABLE IF EXISTS platform_user;
