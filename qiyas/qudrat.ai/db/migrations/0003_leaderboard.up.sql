-- 0003_leaderboard — opt-in flag on users.
--
-- Spec §22 rules: leaderboard is OPT-IN, never auto-enrolled. The flag
-- defaults to false; the /api/me/leaderboard endpoint flips it.

ALTER TABLE users
    ADD COLUMN leaderboard_opt_in boolean NOT NULL DEFAULT false;

-- Helper index for the leaderboard reads — they all filter on this flag
-- before joining to the (large) attempts table.
CREATE INDEX users_leaderboard_optin_idx
    ON users (id)
    WHERE leaderboard_opt_in = true;
