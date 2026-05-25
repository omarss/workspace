-- Control-plane deployments + BYOD + operator audit. Phase 11.
--
-- This migration ships the Deployment resource model, BYOD domain
-- attachments with DNS TXT verification, an operator-action audit chain
-- (mirrors Phase 10 JCS hash-chain but with operator_id as the actor),
-- and a per-deployment provisioning step log used by Phase 12a-e
-- adapters for forward progress + replay safety.
--
-- AGENTS.md §6 (homelab model), §8.0 (control-plane endpoints), §11.5
-- (id prefixes), §12.1 (Deployments module), §18.4 (operator MFA).

CREATE TABLE deployment (
    id                  text PRIMARY KEY CHECK (id LIKE 'dep\_%' ESCAPE '\'),
    project_slug        text NOT NULL CHECK (
                            project_slug ~ '^[a-z][a-z0-9-]*[a-z0-9]$'
                            AND length(project_slug) BETWEEN 2 AND 32),
    environment_slug    text NOT NULL CHECK (
                            environment_slug ~ '^[a-z][a-z0-9-]*[a-z0-9]$'
                            AND length(environment_slug) BETWEEN 2 AND 32),
    region              text,
    modules             text[] NOT NULL DEFAULT '{}',
    image_version       text NOT NULL,
    data_residency      text,
    primary_vhost       text NOT NULL,
    -- status state machine: provisioning -> active -> upgrading -> active
    --                                          \-> failed
    --                                          \-> restoring -> active
    --                                          \-> destroyed -> purged
    status              text NOT NULL DEFAULT 'provisioning'
                        CHECK (status IN (
                            'provisioning','active','suspended','upgrading',
                            'failed','destroying','destroyed','restoring',
                            'purging','purged')),
    db_name             text NOT NULL,
    db_app_role         text NOT NULL,
    namespace           text NOT NULL,
    -- bao_kid equals id in MVP; Phase 12d may diverge after a rotation.
    bao_kid             text NOT NULL,
    metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_event_id       text,
    retain_until        timestamptz,
    row_seq             bigint NOT NULL DEFAULT 1,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_slug, environment_slug)
);

-- bump_row_seq is borrowed from the dataplane schema but the control plane
-- has its own copy because the two databases never share functions. The
-- trigger is the source of ETag-able optimistic concurrency.
CREATE OR REPLACE FUNCTION bump_row_seq() RETURNS trigger AS $$
BEGIN
    NEW.row_seq := OLD.row_seq + 1;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER deployment_bump_row_seq
    BEFORE UPDATE ON deployment
    FOR EACH ROW EXECUTE FUNCTION bump_row_seq();

CREATE TABLE deployment_revision (
    id              text PRIMARY KEY CHECK (id LIKE 'rev\_%' ESCAPE '\'),
    deployment_id   text NOT NULL REFERENCES deployment (id) ON DELETE CASCADE,
    image_version   text NOT NULL,
    applied_at      timestamptz NOT NULL DEFAULT now(),
    is_rolled_back  boolean NOT NULL DEFAULT false,
    applied_by      text NOT NULL,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX deployment_revision_dep_idx ON deployment_revision (deployment_id, applied_at DESC);

CREATE TABLE deployment_domain (
    id                    text PRIMARY KEY CHECK (id LIKE 'dom\_%' ESCAPE '\'),
    deployment_id         text NOT NULL REFERENCES deployment (id) ON DELETE CASCADE,
    domain                text NOT NULL,
    is_primary            boolean NOT NULL DEFAULT false,
    status                text NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending','verified','failed','removed')),
    verification_method   text NOT NULL DEFAULT 'dns_txt'
                          CHECK (verification_method IN ('dns_txt')),
    verification_record   jsonb NOT NULL,
    verification_token    text NOT NULL,
    verified_at           timestamptz,
    last_check_at         timestamptz,
    last_check_error      text,
    -- cert_status is filled by Phase 12a; Phase 11 leaves it at 'pending'.
    cert_status           text NOT NULL DEFAULT 'pending'
                          CHECK (cert_status IN ('pending','issued','renewing','failed','revoked')),
    cert_issued_at        timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX deployment_domain_unique_active
    ON deployment_domain (domain) WHERE status <> 'removed';
CREATE INDEX deployment_domain_dep_idx ON deployment_domain (deployment_id);

-- Per-Deployment provisioning step log. Phase 12a-e adapters write rows
-- here so a partial failure has enough context for the destroy reconciler
-- and operator postmortem.
CREATE TABLE deployment_provision_step (
    id              bigserial PRIMARY KEY,
    deployment_id   text NOT NULL REFERENCES deployment (id) ON DELETE CASCADE,
    step_name       text NOT NULL,
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','completed','failed','rolled_back')),
    started_at      timestamptz,
    completed_at    timestamptz,
    error_message   text,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX deployment_provision_step_dep_idx
    ON deployment_provision_step (deployment_id, id);

-- Operator inventory. Phase 13 layers MFA + IP allowlist + session cap.
CREATE TABLE operator (
    id                text PRIMARY KEY CHECK (id LIKE 'op\_%' ESCAPE '\'),
    email_hash        bytea NOT NULL UNIQUE,
    email_ciphertext  bytea NOT NULL,
    email_wrapped_dek text  NOT NULL,
    email_nonce       bytea NOT NULL,
    email_kid         text  NOT NULL,
    email_key_version integer NOT NULL,
    is_active         boolean NOT NULL DEFAULT true,
    mfa_enabled       boolean NOT NULL DEFAULT false,
    ip_allowlist      text[] NOT NULL DEFAULT '{}',
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

-- Operator audit chain. Mirrors the Phase 10 JCS hash-chain shape
-- (audit_event in the data plane) with operator_id as the actor and a
-- single global chain (no tenant scoping — operator actions can cross
-- deployments). chain_sequence is the monotonic position in the chain.
CREATE TABLE operator_audit_event (
    id              text PRIMARY KEY CHECK (id LIKE 'audit\_%' ESCAPE '\'),
    operator_id     text NOT NULL,
    action          text NOT NULL,
    deployment_id   text,
    resource_type   text,
    resource_id     text,
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    ip_address      text,
    request_id      text,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    chain_sequence  bigint NOT NULL,
    prev_hash       bytea NOT NULL,
    row_hash        bytea NOT NULL,
    UNIQUE (chain_sequence)
);
CREATE INDEX operator_audit_event_op_idx ON operator_audit_event (operator_id, occurred_at DESC);
CREATE INDEX operator_audit_event_dep_idx ON operator_audit_event (deployment_id, occurred_at DESC);

-- Append-only enforcement. The PUBLIC role gets SELECT + INSERT only;
-- updates / deletes raise check_violation via triggers. Mirrors Phase 10.
REVOKE ALL ON operator_audit_event FROM PUBLIC;
GRANT SELECT, INSERT ON operator_audit_event TO PUBLIC;

CREATE OR REPLACE FUNCTION operator_audit_event_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'operator_audit_event is append-only' USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER operator_audit_event_no_update
    BEFORE UPDATE ON operator_audit_event
    FOR EACH ROW EXECUTE FUNCTION operator_audit_event_immutable();
CREATE TRIGGER operator_audit_event_no_delete
    BEFORE DELETE ON operator_audit_event
    FOR EACH ROW EXECUTE FUNCTION operator_audit_event_immutable();
