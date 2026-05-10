-- 0001_init — qudrat Phase 1 schema.
--
-- Covers Phase 1 needs (item bank + 245-question seed) AND lays out the
-- full shape from spec sections 8 and 19 so later phases (auth, attempts,
-- reviewer pipeline, analytics) can land without breaking migrations.
--
-- All identifiers default to gen_random_uuid() (pgcrypto, included since PG 13).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- Auth: created in Phase 1 to avoid churn when Phase 2 wires the OTP flow.
-- Same shape as prompter — SMS goes through Twilio Verify (we only store the
-- SID), email goes through Resend with a locally-bcrypted code.
-- ============================================================================

CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text UNIQUE,
    phone         text UNIQUE,
    nickname      text NOT NULL DEFAULT '',
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz,
    CONSTRAINT users_identifier_present CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

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
CREATE INDEX otp_challenges_identifier_active_idx
    ON otp_challenges (identifier, channel)
    WHERE consumed_at IS NULL;

CREATE TABLE sessions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    refresh_hash text NOT NULL UNIQUE,
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz,
    ip           text,
    ua           text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sessions_user_idx    ON sessions (user_id);
CREATE INDEX sessions_expires_idx ON sessions (expires_at);

-- ============================================================================
-- Item bank: spec §8 schema. Fingerprints + hashes enable spec §9 dedup.
-- ============================================================================

-- A similarity_clusters row groups questions that test the same concept via
-- the same solution path. Phase 1 writes none of these; Phase 7 (reviewer
-- pipeline) populates them from embeddings + fingerprint clustering.
CREATE TABLE similarity_clusters (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    label       text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE items (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Workflow status. Phase 1 imports as 'accepted'; the reviewer pipeline
    -- moves items through draft → needs_review → accepted/rejected.
    status                      text NOT NULL DEFAULT 'accepted'
        CHECK (status IN ('draft','accepted','rejected','retired','needs_review')),

    -- Taxonomy.
    exam_type                   text NOT NULL CHECK (exam_type IN ('qudurat','tahsili')),
    section                     text NOT NULL,
    subject                     text NOT NULL DEFAULT '',
    grade_level                 text NOT NULL DEFAULT 'general',
    unit                        text NOT NULL DEFAULT '',
    topic                       text NOT NULL DEFAULT '',
    skill                       text NOT NULL DEFAULT '',
    cognitive_level             text NOT NULL
        CHECK (cognitive_level IN ('recall','understanding','application','analysis','inference')),

    -- Difficulty: target is what the writer aimed for; calibrated is what
    -- learner data says it actually is. Phase 8 fills the latter.
    difficulty_target           text NOT NULL CHECK (difficulty_target IN ('easy','medium','hard')),
    difficulty_calibrated       numeric,

    -- Question shape.
    question_archetype          text NOT NULL DEFAULT '',
    question_text               text NOT NULL,
    correct_answer              char(1) NOT NULL CHECK (correct_answer IN ('A','B','C','D')),
    explanation                 text NOT NULL DEFAULT '',
    estimated_time_seconds      int  NOT NULL DEFAULT 60,

    -- Spec §9.1/9.2 dedup keys.
    concept_fingerprint         text NOT NULL DEFAULT '',
    solution_fingerprint        text NOT NULL DEFAULT '',
    surface_fingerprint         text NOT NULL DEFAULT '',
    normalized_text_hash        text NOT NULL UNIQUE,
    stem_hash                   text NOT NULL DEFAULT '',
    choices_hash                text NOT NULL DEFAULT '',

    -- Cluster membership (assigned by the reviewer pipeline).
    similarity_cluster_id       uuid REFERENCES similarity_clusters (id),

    -- Provenance.
    source                      text NOT NULL DEFAULT 'llm_generated',
    model_name                  text,
    generation_prompt_version   text,
    review_prompt_version       text,

    -- Quality scores from reviewer LLM (spec §12).
    quality_score               numeric,
    novelty_score               numeric,
    ambiguity_score             numeric,
    novelty_notes               text NOT NULL DEFAULT '',

    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX items_taxonomy_idx
    ON items (exam_type, section, topic, difficulty_target);
CREATE INDEX items_cluster_idx
    ON items (similarity_cluster_id)
    WHERE similarity_cluster_id IS NOT NULL;
CREATE INDEX items_status_idx
    ON items (status)
    WHERE status = 'accepted';

CREATE TABLE item_choices (
    item_id              uuid NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    choice_key           char(1) NOT NULL CHECK (choice_key IN ('A','B','C','D')),
    choice_text          text NOT NULL,
    distractor_rationale text NOT NULL DEFAULT '',
    PRIMARY KEY (item_id, choice_key)
);

CREATE TABLE item_tags (
    item_id uuid NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    tag     text NOT NULL,
    PRIMARY KEY (item_id, tag)
);
CREATE INDEX item_tags_tag_idx ON item_tags (tag);

-- ============================================================================
-- Attempts: spec §20 (no-repeat) and §21 (adaptive). Created in Phase 1 so
-- migrations stay additive when Phase 3 wires the practice API.
-- ============================================================================

-- served_items enforces the spec §20 "never serve the same question twice
-- to the same user" rule. Lookup by (user_id, item_id) is a primary-key
-- probe; the secondary index supports the "what did this user see recently"
-- timeline view.
CREATE TABLE served_items (
    user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    item_id    uuid NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    served_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, item_id)
);
CREATE INDEX served_items_user_recent_idx
    ON served_items (user_id, served_at DESC);

CREATE TABLE attempts (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    item_id        uuid NOT NULL REFERENCES items (id),
    choice_key     char(1) CHECK (choice_key IN ('A','B','C','D')),
    correct        boolean,
    time_taken_ms  int,
    hint_used      boolean NOT NULL DEFAULT false,
    served_at      timestamptz NOT NULL DEFAULT now(),
    answered_at    timestamptz
);
CREATE INDEX attempts_user_recent_idx
    ON attempts (user_id, served_at DESC);
CREATE INDEX attempts_item_idx
    ON attempts (item_id);
