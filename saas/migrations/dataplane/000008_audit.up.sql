-- Phase 10 — Audit logs.
--
-- AGENTS.md §8.6 / §18.3 define the surface: append-only audit_event
-- table with a per-tenant SHA-256 hash chain. Each row stores
--   prev_hash = row_hash of the prior row (or Genesis(tenant_id))
--   row_hash  = sha256(prev_hash || JCS(canonical body))
-- so any in-place tampering of a single row breaks the chain at that
-- sequence number.
--
-- Append-only enforcement is layered (defence in depth):
--
--   1. RLS policy scopes reads to current_setting('app.current_tenant_id').
--   2. Postgres grants REVOKE UPDATE / DELETE from PUBLIC; the per-deployment
--      app role inherits SELECT + INSERT only. Phase 11c tightens the
--      grants to a dedicated role; the placeholder GRANT TO PUBLIC keeps
--      MVP single-DB dev working.
--   3. BEFORE UPDATE / DELETE triggers raise an exception even if a
--      superuser session attempts the operation accidentally. Defence
--      against an admin tooling foot-gun, not against a determined
--      attacker with raw SQL access (that's a separate threat model —
--      see Open Questions §10.x of the plan).
--
-- The chain is NOT computed inside Postgres. RFC 8785 JCS canonicalisation
-- is too risky to maintain in plpgsql; the Go subscriber owns the hash
-- math and only the sequence-assignment trigger lives in-DB.

CREATE TABLE audit_event (
    id              text PRIMARY KEY CHECK (id LIKE 'audit\_%' ESCAPE '\'),

    -- tenant_id is NOT a FK because audit rows must outlive tenant
    -- soft-delete; we still want the chain verifiable after a tenant
    -- is purged (AGENTS.md §18.6: emit `tenant.purged` BEFORE the row
    -- disappears, then keep the audit history).
    tenant_id       text NOT NULL,

    actor_type      text NOT NULL CHECK (actor_type IN (
        'user',
        'api_key',
        'operator',
        'operator_impersonation',
        'system'
    )),
    actor_id        text NOT NULL,

    action          text NOT NULL,
    resource_type   text NOT NULL,
    resource_id     text,

    occurred_at     timestamptz NOT NULL DEFAULT now(),

    -- PII-tagged: ip_address + user_agent. Plaintext for MVP; envelope
    -- columns reserved for the v1 "encrypt PII in audit" follow-up.
    ip_address      text,
    user_agent      text,
    request_id      text,

    -- JSON metadata. Subscribers strip top-level redacted keys via
    -- internal/platform/log.IsRedactedKey before insert; deep PII inside
    -- nested objects is the subscriber's responsibility per the §18.5
    -- redactor list.
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- Outbox lineage. The subscriber writes this; it makes the audit
    -- subscriber idempotent (re-delivery of the same outbox row no-ops
    -- via the unique index below).
    source_event_id text,

    -- Hash chain columns. 32-byte SHA-256 outputs.
    prev_hash       bytea NOT NULL,
    row_hash        bytea NOT NULL,
    chain_sequence  bigint NOT NULL,

    UNIQUE (tenant_id, chain_sequence)
);

-- Idempotency: at most one audit row per outbox event. Partial index
-- lets nullable source_event_id (e.g. operator-direct events) coexist.
CREATE UNIQUE INDEX audit_event_source_event_idx
    ON audit_event (source_event_id)
    WHERE source_event_id IS NOT NULL;

-- Browse / filter indices per AGENTS.md §8.6.
CREATE INDEX audit_event_tenant_time_idx
    ON audit_event (tenant_id, occurred_at DESC);
CREATE INDEX audit_event_action_idx
    ON audit_event (tenant_id, action, occurred_at DESC);
CREATE INDEX audit_event_resource_idx
    ON audit_event (tenant_id, resource_type, resource_id);
CREATE INDEX audit_event_actor_idx
    ON audit_event (tenant_id, actor_id, occurred_at DESC);

ALTER TABLE audit_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_event FORCE  ROW LEVEL SECURITY;
CREATE POLICY audit_event_tenant_only ON audit_event
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- Append-only grants. Phase 11c tightens to a dedicated app role; for
-- the single-DB MVP we operate on PUBLIC and rely on the trigger as the
-- enforcement boundary the test suite can exercise without a role
-- switch.
REVOKE ALL    ON audit_event FROM PUBLIC;
GRANT SELECT, INSERT ON audit_event TO PUBLIC;

-- Triggers reject UPDATE / DELETE explicitly so an operator running
-- `make db-shell` cannot accidentally rewrite history. RAISE EXCEPTION
-- yields error code P0001 — the verifier's tamper integration test
-- expects this code.
CREATE OR REPLACE FUNCTION audit_event_no_update() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'audit_event is append-only; UPDATE forbidden (id=%, tenant=%)',
        OLD.id, OLD.tenant_id
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION audit_event_no_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'audit_event is append-only; DELETE forbidden (id=%, tenant=%)',
        OLD.id, OLD.tenant_id
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_event_no_update_trg
    BEFORE UPDATE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION audit_event_no_update();

CREATE TRIGGER audit_event_no_delete_trg
    BEFORE DELETE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION audit_event_no_delete();

-- Permission catalogue addition. `audit.read` gates the read endpoints
-- once the v1 RBAC hardening pass turns it on; MVP only enforces
-- AssertTenant (CONVENTIONS.md §2 retrofit table is unchanged in
-- Phase 10 — see ADR 012 + Phase 10 plan §10.7).
INSERT INTO permission (id, resource_type, action, description, module) VALUES
    ('perm_audit_read', 'audit', 'read', 'Read audit events for a tenant', 'audit')
ON CONFLICT (resource_type, action) DO NOTHING;
