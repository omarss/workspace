-- Phase 9 — API keys.
--
-- AGENTS.md §8.5 + §18.2 define the surface: CRUD + rotate + revoke,
-- argon2id-hashed secrets, envelope-encrypted prefix-search index, IP
-- allowlist + per-key rate limit metadata, rotation grace window with
-- both old and new bearers valid until grace_expires_at.
--
-- Storage model rationale (ADR 008):
--
--   * The full plaintext bearer is hashed with argon2id (OWASP 2024
--     parameters) and stored as a PHC string in `argon_phc`.
--   * The plaintext prefix is also stored in `prefix` — visible in
--     dashboards for human selection. It is NOT secret on its own; the
--     argon hash is what authenticates a bearer.
--   * The HMAC bucket `prefix_lookup_hash` is the indexed column the
--     auth path uses for O(1) candidate lookup. HMAC key lives in
--     OpenBao KV at secret/data/<deployment_id>/api_keys/prefix_hmac_key.
--   * The envelope-encrypted bucket `prefix_lookup_envelope_*` columns
--     hold a second cryptographic barrier: a snapshot leak of the row
--     alone cannot forge a bearer without also stealing both the HMAC
--     key and the per-deployment Transit key.
--   * Rotation stores the predecessor argon PHC + grace expiry inline so
--     the auth path can fall through to the predecessor during grace
--     without a separate join.

CREATE TABLE api_key (
    id                              text PRIMARY KEY
                                    CHECK (id LIKE 'apik\_%' ESCAPE '\'),
    tenant_id                       text NOT NULL REFERENCES tenant (id),
    environment_id                  text,
    name                            text NOT NULL,

    -- Visible 11-char prefix shown in dashboards, e.g. "live_AX9BC7D3".
    prefix                          text NOT NULL,

    -- argon2id PHC string of the FULL plaintext bearer (env_prefix_random).
    -- Format: $argon2id$v=19$m=19456,t=2,p=1$<b64 salt>$<b64 hash>
    argon_phc                       text NOT NULL,

    -- Rotation grace: when this row is the current (active) row but a
    -- previous secret is still valid, the previous PHC + its expiry live
    -- here. After grace, sweeper clears both columns.
    predecessor_argon_phc           text,
    predecessor_expires_at          timestamptz,

    -- HMAC bucket of the prefix; indexed for constant-time auth lookup.
    -- The HMAC key is per-deployment, loaded from OpenBao KV once at
    -- process start.
    prefix_lookup_hash              bytea NOT NULL,

    -- Envelope-encrypted prefix bucket (defence in depth). Decrypted
    -- and constant-time-compared against the HMAC bucket at auth time.
    -- AAD = deployment_id|apikey|<api_key_id>|prefix_lookup
    -- (CONVENTIONS.md §10.1 strict-mode walker shape).
    prefix_lookup_ciphertext        bytea NOT NULL,
    prefix_lookup_wrapped_dek       text  NOT NULL,
    prefix_lookup_nonce             bytea NOT NULL,
    prefix_lookup_kid               text  NOT NULL,
    prefix_lookup_key_version       integer NOT NULL,

    scopes                          text[] NOT NULL DEFAULT '{}',
    status                          text   NOT NULL DEFAULT 'active'
                                    CHECK (status IN ('active','revoked','expired')),

    -- Per-key rate limit override (RPM). NULL = use deployment default.
    rate_limit_per_minute           integer
                                    CHECK (rate_limit_per_minute IS NULL OR rate_limit_per_minute > 0),
    -- CIDR strings the bearer is allowed to authenticate from. NULL or
    -- empty array means no IP restriction.
    ip_allowlist                    text[],

    created_by                      text NOT NULL,
    created_at                      timestamptz NOT NULL DEFAULT now(),
    updated_at                      timestamptz NOT NULL DEFAULT now(),
    expires_at                      timestamptz,
    last_used_at                    timestamptz,
    revoked_at                      timestamptz,
    rotated_at                      timestamptz,
    row_seq                         bigint NOT NULL DEFAULT 1
);

-- Auth-path index. The lookup is `WHERE prefix_lookup_hash = $1` plus
-- a status filter; the WHERE clause stays narrow because the HMAC is
-- 32 bytes and effectively unique per active prefix.
CREATE INDEX api_key_prefix_lookup_idx
    ON api_key (prefix_lookup_hash)
    WHERE status = 'active';

-- Tenant-scoped browse index for `GET /v1/tenants/{id}/api-keys`.
CREATE INDEX api_key_tenant_status_idx
    ON api_key (tenant_id, status, created_at DESC);

-- Sweeper index for expired predecessors and key TTL.
CREATE INDEX api_key_predecessor_expires_idx
    ON api_key (predecessor_expires_at)
    WHERE predecessor_expires_at IS NOT NULL;
CREATE INDEX api_key_expires_idx
    ON api_key (expires_at)
    WHERE expires_at IS NOT NULL AND status = 'active';

CREATE TRIGGER api_key_bump_row_seq
    BEFORE UPDATE ON api_key
    FOR EACH ROW EXECUTE FUNCTION bump_row_seq();

ALTER TABLE api_key ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_key FORCE  ROW LEVEL SECURITY;
CREATE POLICY api_key_tenant_only ON api_key
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- Permissions: apikey.read and apikey.write already exist in the
-- catalogue from Phase 8 (000006_authorization.up.sql lines 132-133).
-- ON CONFLICT DO NOTHING keeps this migration idempotent in case an
-- operator manually seeded them in a hotfix branch.
INSERT INTO permission (id, resource_type, action, description, module) VALUES
    ('perm_apikey_read',  'apikey', 'read',  'Read API keys',   'apikeys'),
    ('perm_apikey_write', 'apikey', 'write', 'Manage API keys', 'apikeys')
ON CONFLICT (resource_type, action) DO NOTHING;

GRANT SELECT, INSERT, UPDATE, DELETE ON api_key TO PUBLIC;
