-- Notifications (Phase 6): notification_channel, notification_workflow,
-- notification, notification_attempt.
--
-- BYOK vendor credentials are PII / sensitive (ADR 017). Each channel stores
-- the per-Deployment SMTP / SendGrid / SES credentials behind the standard
-- five-column envelope set (ciphertext / wrapped_dek / nonce / kid /
-- key_version). The Go domain type carries a sibling SecretsEnvelope of
-- type crypto.Envelope; the strict-mode persistence walker enforces the
-- pairing.
--
-- Rotation is a distinct verb (ADR 017): the PATCH endpoint never accepts
-- credentials. Every rotation bumps last_rotated_at and row_seq, and an
-- outbox row (notification_channel.rotated) is emitted.
--
-- Per CONVENTIONS.md §4: tenant_id index, RLS + FORCE, row_seq trigger.

CREATE TABLE notification_channel (
    id                    text PRIMARY KEY
                          CHECK (id LIKE 'chan\_%' ESCAPE '\'),
    tenant_id             text NOT NULL REFERENCES tenant (id),

    provider              text NOT NULL
                          CHECK (provider IN ('smtp', 'sendgrid', 'ses', 'in_app')),
    name                  text NOT NULL CHECK (length(name) BETWEEN 1 AND 64),
    -- Non-secret config (host, port, from address, region). JSON object;
    -- the application validates the per-provider shape at the handler.
    config                jsonb NOT NULL DEFAULT '{}'::jsonb
                          CHECK (jsonb_typeof(config) = 'object'),

    -- BYOK envelope set. The plaintext is a provider-shaped JSON payload
    -- (e.g. {"password":"…"} for SMTP, {"api_key":"…"} for SendGrid). The
    -- five columns may be NULL only for the in_app provider, which carries
    -- no external creds. The application enforces the constraint.
    secrets_ciphertext    bytea,
    secrets_wrapped_dek   text,
    secrets_nonce         bytea,
    secrets_kid           text,
    secrets_key_version   integer,

    is_default_for        text[] NOT NULL DEFAULT '{}',
    status                text NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'disabled')),

    -- Mapping into Novu: after the channel-creation outbox event is consumed,
    -- the platform pushes an integration record to Novu and stores the
    -- returned integration id here. NULL until the worker syncs.
    novu_integration_id   text,

    last_rotated_at       timestamptz,
    row_seq               bigint NOT NULL DEFAULT 1,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    deleted_at            timestamptz
);

-- Per-tenant uniqueness on the operator-friendly name. Soft-deleted rows
-- don't block re-use.
CREATE UNIQUE INDEX notification_channel_name_unique
    ON notification_channel (tenant_id, name)
    WHERE deleted_at IS NULL;
CREATE INDEX notification_channel_tenant_idx
    ON notification_channel (tenant_id, status) WHERE deleted_at IS NULL;

CREATE TRIGGER notification_channel_bump_row_seq
    BEFORE UPDATE ON notification_channel
    FOR EACH ROW EXECUTE FUNCTION bump_row_seq();

ALTER TABLE notification_channel ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_channel FORCE  ROW LEVEL SECURITY;
CREATE POLICY notification_channel_tenant_only ON notification_channel
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- Workflow mapping. Templates live in Novu; the platform stores only the
-- name -> Novu workflow id mapping plus a short description.
CREATE TABLE notification_workflow (
    id                  text PRIMARY KEY
                        CHECK (id LIKE 'wf\_%' ESCAPE '\'),
    tenant_id           text NOT NULL REFERENCES tenant (id),
    name                text NOT NULL CHECK (length(name) BETWEEN 1 AND 64),
    novu_workflow_id    text NOT NULL,
    description         text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
CREATE INDEX notification_workflow_tenant_idx
    ON notification_workflow (tenant_id);
ALTER TABLE notification_workflow ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_workflow FORCE  ROW LEVEL SECURITY;
CREATE POLICY notification_workflow_tenant_only ON notification_workflow
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- Notification record. The payload is envelope-encrypted (it may contain
-- arbitrary PII supplied by the caller — see SendNotificationRequest).
CREATE TABLE notification (
    id                      text PRIMARY KEY
                            CHECK (id LIKE 'notif\_%' ESCAPE '\'),
    tenant_id               text NOT NULL REFERENCES tenant (id),
    workflow_name           text NOT NULL,
    to_user_id              text NOT NULL REFERENCES platform_user (id),

    -- Payload envelope set. NOT NULL — every send carries at least an
    -- empty object so the envelope walker has something to encrypt; this
    -- preserves the kid binding even for "trivial" sends.
    payload_ciphertext      bytea NOT NULL,
    payload_wrapped_dek     text  NOT NULL,
    payload_nonce           bytea NOT NULL,
    payload_kid             text  NOT NULL,
    payload_key_version     integer NOT NULL,

    novu_transaction_id     text,
    status                  text NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued', 'sent', 'delivered', 'failed')),
    queued_at               timestamptz NOT NULL DEFAULT now(),
    sent_at                 timestamptz,
    delivered_at            timestamptz,
    failed_at               timestamptz,
    failure_reason          text,
    row_seq                 bigint NOT NULL DEFAULT 1
);
CREATE INDEX notification_status_idx
    ON notification (tenant_id, status, queued_at DESC);
CREATE INDEX notification_user_idx
    ON notification (tenant_id, to_user_id, queued_at DESC);

CREATE TRIGGER notification_bump_row_seq
    BEFORE UPDATE ON notification
    FOR EACH ROW EXECUTE FUNCTION bump_row_seq();

ALTER TABLE notification ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification FORCE  ROW LEVEL SECURITY;
CREATE POLICY notification_tenant_only ON notification
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- Per-attempt log. Phase 6 records rows but does not yet act on them (full
-- retry strategy is a v1 roadmap item — Phase 6 leaves Novu's own queue
-- as the retry source of truth).
CREATE TABLE notification_attempt (
    id                  bigserial PRIMARY KEY,
    notification_id     text NOT NULL REFERENCES notification (id) ON DELETE CASCADE,
    attempted_at        timestamptz NOT NULL DEFAULT now(),
    status              text NOT NULL CHECK (status IN ('queued', 'sent', 'failed')),
    failure_reason      text
);
CREATE INDEX notification_attempt_notif_idx
    ON notification_attempt (notification_id, attempted_at DESC);

-- App role grants. Phase 11c tightens to per-Deployment app roles.
GRANT SELECT, INSERT, UPDATE, DELETE ON notification_channel   TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON notification_workflow  TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON notification           TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON notification_attempt   TO PUBLIC;
GRANT USAGE,  SELECT                  ON SEQUENCE notification_attempt_id_seq TO PUBLIC;
