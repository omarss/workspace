-- Tenants: the unit of isolation within a Deployment.
--
-- Tenant is special because tenant_id IS its primary id; subsequent tenant-bound
-- tables hold a tenant_id column. RLS policy is therefore "id = current_tenant".
-- The pgx pool's AfterAcquire hook will SET LOCAL app.current_tenant_id on every
-- connection borrowed from the pool — without that hook RLS silently returns
-- empty result sets (Phase 2 anti-pattern guard).

CREATE TABLE tenant (
    id                      text PRIMARY KEY
                            CHECK (id LIKE 'tenant\_%' ESCAPE '\'),
    slug                    text NOT NULL UNIQUE,
    name                    text NOT NULL,
    status                  text NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'suspended', 'deleted')),
    default_organization_id text,
    metadata                jsonb NOT NULL DEFAULT '{}'::jsonb
                            CHECK (jsonb_typeof(metadata) = 'object'),
                            -- Phase 2 enforces the 16-key cap at the API layer
                            -- (OpenAPI schema + service.validateMetadata). A DB
                            -- check would require a subquery, which Postgres
                            -- disallows in CHECK constraints; a trigger lands
                            -- in Phase 3 alongside the platform-pattern promotion.
    row_seq                 bigint NOT NULL DEFAULT 1,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz
);

CREATE UNIQUE INDEX tenant_slug_active_idx ON tenant (slug) WHERE deleted_at IS NULL;
CREATE INDEX tenant_status_idx             ON tenant (status) WHERE deleted_at IS NULL;
CREATE INDEX tenant_created_at_idx         ON tenant (created_at DESC);

-- ETag sequence trigger: on every UPDATE bump row_seq and updated_at. The Weak
-- ETag returned in HTTP responses is W/"v<row_seq>"; PATCH/DELETE require it
-- in If-Match (412 on stale).
CREATE OR REPLACE FUNCTION bump_row_seq() RETURNS trigger AS $$
BEGIN
    NEW.row_seq    := OLD.row_seq + 1;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tenant_bump_row_seq
    BEFORE UPDATE ON tenant
    FOR EACH ROW EXECUTE FUNCTION bump_row_seq();

-- Row-Level Security. FORCE applies the policy even to the table owner so a
-- buggy admin connection cannot bypass it. The policy reads the per-request
-- GUC set by the pgx AfterAcquire hook (defense layer 3 of tenant isolation).
ALTER TABLE tenant ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_self_only ON tenant
    USING (id = current_setting('app.current_tenant_id', true));

-- Outbox table. Every module's domain events land here in the same transaction
-- as the state change; an in-process dispatcher polls and publishes (ADR 009).
-- tenant_id is nullable for cross-tenant events such as deployment-level audit.
CREATE TABLE outbox_event (
    id                bigserial PRIMARY KEY,
    event_id          text NOT NULL UNIQUE CHECK (event_id LIKE 'evt\_%' ESCAPE '\'),
    type              text NOT NULL,
    event_version     integer NOT NULL DEFAULT 1,
    tenant_id         text,
    deployment_id     text NOT NULL,
    occurred_at       timestamptz NOT NULL DEFAULT now(),
    payload           jsonb NOT NULL,
    published_at      timestamptz,
    delivery_attempts integer NOT NULL DEFAULT 0,
    last_error        text
);
CREATE INDEX outbox_unpublished_idx ON outbox_event (id) WHERE published_at IS NULL;

-- Idempotency record table. Stores body hash + cached response per (tenant,
-- key, route, method) tuple. The 24-hour expiry window matches the Stripe-style
-- semantics from AGENTS.md section 5.2 (ADR 010).
CREATE TABLE idempotency_record (
    id                bigserial PRIMARY KEY,
    tenant_id         text NOT NULL,
    idempotency_key   text NOT NULL,
    route             text NOT NULL,
    method            text NOT NULL,
    request_body_hash bytea NOT NULL,
    response_status   integer,
    response_headers  jsonb NOT NULL DEFAULT '{}'::jsonb,
    response_body     bytea,
    in_flight         boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    expires_at        timestamptz NOT NULL,
    UNIQUE (tenant_id, idempotency_key, route, method)
);
CREATE INDEX idempotency_expiry_idx ON idempotency_record (expires_at);

ALTER TABLE idempotency_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_record FORCE  ROW LEVEL SECURITY;
CREATE POLICY idempotency_tenant_only ON idempotency_record
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- App role grants. Phase 2 uses the default migration role (the connection that
-- ran this file) and the dev `saas` user — PUBLIC is the lowest-friction
-- placeholder. Phase 11c tightens these to per-Deployment app roles with
-- explicit GRANTs and revokes UPDATE/DELETE on outbox_event after publish.
GRANT SELECT, INSERT, UPDATE, DELETE ON tenant                  TO PUBLIC;
GRANT SELECT, INSERT, UPDATE         ON outbox_event            TO PUBLIC;
GRANT USAGE,  SELECT ON SEQUENCE outbox_event_id_seq            TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_record      TO PUBLIC;
GRANT USAGE,  SELECT ON SEQUENCE idempotency_record_id_seq      TO PUBLIC;
