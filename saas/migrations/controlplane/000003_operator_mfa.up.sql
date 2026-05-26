-- Phase 13 — Operator MFA / step-up / IP allowlist + impersonation session.
--
-- Extends the operator inventory shipped in Phase 11 (migration 000002):
--   - keycloak_user_id, email, name      — the realm-linked identity fields
--     needed for ip-allowlist lookup by JWT subject; Phase 11 stored only
--     hashed / encrypted email which is opaque to the JWT path.
--   - amr / last_step_up_at              — MFA / step-up audit hints
--   - mfa_required                       — operators can opt out of MFA
--     ONLY for break-glass system accounts; defaults to true. Combined
--     with the operators realm's required actions this means the only
--     legitimate `false` rows are short-lived emergency accounts.
--
-- Adds:
--   impersonation_session — append-only log of operator impersonation
--     tokens minted by the control plane. The token itself is signed
--     by the platform (not Keycloak) and short-lived (≤15 min); this
--     table records the metadata for audit + revocation. Once a row's
--     ended_at is set, the data-plane auth middleware refuses the JWT
--     even if it has not yet expired.
--
-- AGENTS.md §18.4 (operator auth model + impersonation),
-- §18.3 (audit list — operator.impersonation_started / _ended).
-- Plan: docs/plans/mvp/14-impersonation-operator-mfa.md §13.2 + §13.6.

ALTER TABLE operator
    ADD COLUMN keycloak_user_id text UNIQUE,
    ADD COLUMN email            text,
    ADD COLUMN name             text,
    ADD COLUMN amr              text[] NOT NULL DEFAULT '{}',
    ADD COLUMN last_step_up_at  timestamptz,
    ADD COLUMN mfa_required     boolean NOT NULL DEFAULT true;

-- A unique index on email (when non-null) keeps the column lookup-by-email
-- path cheap without forcing legacy Phase 11 rows (where email_ciphertext
-- was the only address store) to backfill.
CREATE UNIQUE INDEX operator_email_idx ON operator (email) WHERE email IS NOT NULL;

CREATE TABLE impersonation_session (
    id                  text PRIMARY KEY CHECK (id LIKE 'impses\_%' ESCAPE '\'),
    deployment_id       text NOT NULL REFERENCES deployment (id) ON DELETE CASCADE,
    operator_id         text NOT NULL,
    operator_email      text NOT NULL,
    target_member_id    text,
    target_tenant_id    text NOT NULL,
    reason              text NOT NULL CHECK (length(reason) BETWEEN 1 AND 256),
    duration_seconds    integer NOT NULL CHECK (duration_seconds BETWEEN 60 AND 900),
    issued_at           timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz NOT NULL,
    ended_at            timestamptz,
    ended_reason        text CHECK (ended_reason IS NULL
                            OR ended_reason IN ('operator_request','expired','revoked'))
);
CREATE INDEX impersonation_session_op_idx        ON impersonation_session (operator_id, issued_at DESC);
CREATE INDEX impersonation_session_dep_idx       ON impersonation_session (deployment_id, issued_at DESC);
CREATE INDEX impersonation_session_active_idx
    ON impersonation_session (deployment_id, expires_at)
    WHERE ended_at IS NULL;

-- Append-only-ish: rows can only be UPDATE'd to set ended_at + ended_reason,
-- never to modify any other column. Mirrors the operator_audit_event
-- guards from Phase 11.
CREATE OR REPLACE FUNCTION impersonation_session_immutable() RETURNS trigger AS $$
BEGIN
    IF (TG_OP = 'UPDATE') THEN
        IF NEW.id                IS DISTINCT FROM OLD.id
           OR NEW.deployment_id  IS DISTINCT FROM OLD.deployment_id
           OR NEW.operator_id    IS DISTINCT FROM OLD.operator_id
           OR NEW.operator_email IS DISTINCT FROM OLD.operator_email
           OR NEW.target_member_id IS DISTINCT FROM OLD.target_member_id
           OR NEW.target_tenant_id IS DISTINCT FROM OLD.target_tenant_id
           OR NEW.reason          IS DISTINCT FROM OLD.reason
           OR NEW.duration_seconds IS DISTINCT FROM OLD.duration_seconds
           OR NEW.issued_at       IS DISTINCT FROM OLD.issued_at
           OR NEW.expires_at      IS DISTINCT FROM OLD.expires_at THEN
            RAISE EXCEPTION 'impersonation_session columns are immutable except ended_at / ended_reason'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'impersonation_session does not allow this operation'
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER impersonation_session_no_destructive_update
    BEFORE UPDATE ON impersonation_session
    FOR EACH ROW EXECUTE FUNCTION impersonation_session_immutable();

CREATE TRIGGER impersonation_session_no_delete
    BEFORE DELETE ON impersonation_session
    FOR EACH ROW EXECUTE FUNCTION impersonation_session_immutable();
