DROP INDEX IF EXISTS users_leaderboard_optin_idx;
ALTER TABLE users DROP COLUMN IF EXISTS leaderboard_opt_in;
