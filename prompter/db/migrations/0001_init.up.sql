-- 0001_init — prompter Phase 1 schema.
--
-- All identifiers default to gen_random_uuid() (pgcrypto, included since PG 13).
-- Tenant-style isolation is not used here: the game is single-tenant. RLS may
-- come later if user-private data (e.g. submission histories) needs hardening
-- against accidental SELECT * disclosure in admin tooling.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Players. Either email or phone must be present (the row is the OTP target).
CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text UNIQUE,
    phone         text UNIQUE,
    display_name  text NOT NULL DEFAULT '',
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz,
    CONSTRAINT users_identifier_present CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

-- One-time-password challenges. The plaintext code never lands here. The
-- two channels store the verification secret differently:
--   email: we own the secret, code_hash = bcrypt(code).
--   sms:   Twilio Verify owns the secret, provider_ref = Verify SID.
-- Exactly one of the two columns is set, enforced by a CHECK constraint.
-- `attempts` caps brute-force on the email path; Twilio caps it on the SMS path.
CREATE TABLE otp_challenges (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    channel      text NOT NULL CHECK (channel IN ('email','sms')),
    identifier   text NOT NULL,
    code_hash    text,
    provider_ref text,
    attempts     int  NOT NULL DEFAULT 0,
    expires_at   timestamptz NOT NULL,
    consumed_at  timestamptz,
    ip           text,
    ua           text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT otp_secret_present CHECK (
        (channel = 'email' AND code_hash    IS NOT NULL AND provider_ref IS NULL)
        OR
        (channel = 'sms'   AND provider_ref IS NOT NULL AND code_hash    IS NULL)
    )
);
-- Lookups during /verify use (identifier, channel) and discard already-consumed
-- rows. Partial index keeps it small even after months of traffic.
CREATE INDEX otp_challenges_identifier_active_idx
    ON otp_challenges (identifier, channel)
    WHERE consumed_at IS NULL;

-- Refresh tokens. Only the SHA-256 of the token is stored; the cookie carries
-- the plaintext. Revocation is a one-way write to revoked_at.
CREATE TABLE sessions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    refresh_hash text NOT NULL UNIQUE,
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz,
    ip           text,
    ua           text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sessions_user_idx    ON sessions (user_id);
CREATE INDEX sessions_expires_idx ON sessions (expires_at);

-- Available LLM tiers, seeded by a later migration. Kept as data (not code)
-- so an admin can disable a model without redeploying.
CREATE TABLE models (
    slug          text PRIMARY KEY,
    display_name  text NOT NULL,
    provider      text NOT NULL,
    param_count_b numeric(6,2) NOT NULL,
    multiplier    numeric(6,2) NOT NULL,
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Game challenges. `test_suite` is the hidden grader: an opaque JSON
-- structure interpreted by the language-specific runner in internal/grading.
CREATE TABLE challenges (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text NOT NULL UNIQUE,
    title       text NOT NULL,
    modality    text NOT NULL CHECK (modality IN ('code','image','video','ui')),
    language    text NOT NULL,
    difficulty  text NOT NULL CHECK (difficulty IN ('easy','medium','hard','extreme')),
    target_code text NOT NULL,
    test_suite  jsonb NOT NULL,
    active_from timestamptz NOT NULL DEFAULT now(),
    active_to   timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX challenges_modality_active_idx
    ON challenges (modality, active_from);

-- One challenge per calendar day across all users. Daily mode = same target
-- for everyone, leaderboard contested.
CREATE TABLE daily_challenges (
    challenge_date date PRIMARY KEY,
    challenge_id   uuid NOT NULL REFERENCES challenges (id),
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- Player attempts. Status moves queued → running → graded (or rejected).
-- Numeric precisions chosen for clean JSON serialization without exponent.
CREATE TABLE submissions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    challenge_id  uuid NOT NULL REFERENCES challenges (id),
    model_slug    text NOT NULL REFERENCES models (slug),
    prompt        text NOT NULL,
    prompt_tokens int  NOT NULL,
    output_code   text,
    similarity    numeric(6,5),
    tests_passed  int,
    tests_total   int,
    multiplier    numeric(6,2),
    brevity       numeric(8,5),
    score         numeric(10,2),
    status        text NOT NULL CHECK (status IN ('queued','running','graded','rejected')),
    reject_reason text,
    seed          bigint NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    graded_at     timestamptz
);
CREATE INDEX submissions_user_created_idx
    ON submissions (user_id, created_at DESC);
CREATE INDEX submissions_challenge_score_idx
    ON submissions (challenge_id, score DESC NULLS LAST);
-- Worker poll path: cheap scan over only the queued slice.
CREATE INDEX submissions_status_queued_idx
    ON submissions (created_at)
    WHERE status = 'queued';

-- ELO per (player, modality). Phase 1 only writes 'code'; the modality column
-- exists so image/video/ui ratings can land later without migration.
CREATE TABLE ratings (
    user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    modality     text NOT NULL,
    elo          numeric(8,2) NOT NULL DEFAULT 1500,
    games_played int  NOT NULL DEFAULT 0,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, modality)
);
