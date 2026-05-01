-- Reverse order to satisfy FK dependencies.
DROP TABLE IF EXISTS ratings;
DROP TABLE IF EXISTS submissions;
DROP TABLE IF EXISTS daily_challenges;
DROP TABLE IF EXISTS challenges;
DROP TABLE IF EXISTS models;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS otp_challenges;
DROP TABLE IF EXISTS users;
-- pgcrypto is left in place: removing an extension owned by other roles
-- causes errors in shared dev databases. The DROP is a no-op anyway.
