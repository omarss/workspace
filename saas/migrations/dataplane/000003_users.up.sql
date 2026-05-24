-- Identity (Phase 5): platform_user + identity_provider_mapping + social_login_state.
--
-- Email is PII; per CONVENTIONS.md §10.1 we carry the five-column envelope
-- set (ciphertext, wrapped_dek, nonce, kid, key_version). The Go struct also
-- declares a sibling <Field>Envelope field; the strict-mode persistence
-- walker enforces that pairing at compile-time of the repo path.
--
-- The HMAC-SHA256 email_lookup_hash backs per-tenant uniqueness without ever
-- storing plaintext. The HMAC key lives in OpenBao KV at
-- secret/data/<deployment_id>/identity/email_hmac_key (per AGENTS.md §18.7).

CREATE TABLE platform_user (
    id                      text PRIMARY KEY
                            CHECK (id LIKE 'user\_%' ESCAPE '\'),
    tenant_id               text NOT NULL REFERENCES tenant (id),

    -- Email PII envelope columns. NOT NULL because every user must have an
    -- email; the platform refuses creates without one.
    email_lookup_hash       bytea NOT NULL,
    email_ciphertext        bytea NOT NULL,
    email_wrapped_dek       text  NOT NULL,
    email_nonce             bytea NOT NULL,
    email_kid               text  NOT NULL,
    email_key_version       integer NOT NULL,
    email_verified          boolean NOT NULL DEFAULT false,

    -- Optional PII fields. NULL when the user has not supplied them. The
    -- envelope columns are NULL-by-default; the persistence walker checks
    -- before issuing a decrypt call.
    name_ciphertext         bytea,
    name_wrapped_dek        text,
    name_nonce              bytea,
    name_kid                text,
    name_key_version        integer,

    phone_ciphertext        bytea,
    phone_wrapped_dek       text,
    phone_nonce             bytea,
    phone_kid               text,
    phone_key_version       integer,

    keycloak_user_id        text NOT NULL UNIQUE,
    status                  text NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'disabled', 'deleted')),
    metadata                jsonb NOT NULL DEFAULT '{}'::jsonb
                            CHECK (jsonb_typeof(metadata) = 'object'),
    row_seq                 bigint NOT NULL DEFAULT 1,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz
);

-- Per-tenant uniqueness: same email may exist across tenants.
CREATE UNIQUE INDEX platform_user_email_unique
    ON platform_user (tenant_id, email_lookup_hash)
    WHERE deleted_at IS NULL;
CREATE INDEX platform_user_tenant_status_idx
    ON platform_user (tenant_id, status) WHERE deleted_at IS NULL;
CREATE INDEX platform_user_tenant_created_idx
    ON platform_user (tenant_id, created_at DESC);

CREATE TRIGGER platform_user_bump_row_seq
    BEFORE UPDATE ON platform_user
    FOR EACH ROW EXECUTE FUNCTION bump_row_seq();

ALTER TABLE platform_user ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform_user FORCE  ROW LEVEL SECURITY;
CREATE POLICY platform_user_tenant_only ON platform_user
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- Identity provider mapping (social login linkages).
CREATE TABLE identity_provider_mapping (
    platform_user_id   text NOT NULL REFERENCES platform_user (id) ON DELETE CASCADE,
    tenant_id          text NOT NULL,
    provider           text NOT NULL CHECK (provider IN ('google', 'github', 'apple')),
    -- external_subject is the IdP's "sub" claim. Marked sensitive in OpenAPI
    -- but not PII per se — the value is hashed elsewhere (Keycloak) and we
    -- store the raw value to support unlink + audit.
    external_subject   text NOT NULL,
    linked_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (platform_user_id, provider),
    UNIQUE (provider, external_subject)
);
CREATE INDEX identity_provider_mapping_tenant_idx
    ON identity_provider_mapping (tenant_id);
ALTER TABLE identity_provider_mapping ENABLE ROW LEVEL SECURITY;
ALTER TABLE identity_provider_mapping FORCE  ROW LEVEL SECURITY;
CREATE POLICY ipm_tenant_only ON identity_provider_mapping
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- Social login state row (CSRF + return_to binding; 5 min TTL).
-- The state column is opaque random; nothing here is PII. expires_at is
-- swept by a periodic job (TODO: cleanup ticker mirrors the idempotency one).
CREATE TABLE social_login_state (
    state              text PRIMARY KEY,
    tenant_id          text NOT NULL,
    platform_user_id   text NOT NULL,
    provider           text NOT NULL CHECK (provider IN ('google', 'github', 'apple')),
    return_to          text NOT NULL,
    nonce              text NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    expires_at         timestamptz NOT NULL,
    consumed_at        timestamptz
);
CREATE INDEX social_login_state_expiry_idx ON social_login_state (expires_at);
CREATE INDEX social_login_state_tenant_idx ON social_login_state (tenant_id);
ALTER TABLE social_login_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE social_login_state FORCE  ROW LEVEL SECURITY;
CREATE POLICY sls_tenant_only ON social_login_state
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- App role grants. Phase 11c tightens these to per-Deployment app roles.
GRANT SELECT, INSERT, UPDATE, DELETE ON platform_user                TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON identity_provider_mapping    TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON social_login_state           TO PUBLIC;
