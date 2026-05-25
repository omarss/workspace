-- Phase 8 — RBAC-with-domains on Casbin v2.
--
-- This migration ships the authorization plane: the Casbin rule store, the
-- per-tenant role catalogue, the deployment-wide permission catalogue, and
-- the member-role assignment denormalisation.
--
-- Why these tables: AGENTS.md §8.4 mandates pure RBAC (no ReBAC) and §18.1
-- layer 6 makes Casbin's RBAC-with-domains the chosen model. The matcher is
-- `g(r.sub, p.sub, r.dom) && r.dom == p.dom && r.obj == p.obj && r.act == p.act`
-- — strict equality on dom encodes per-tenant isolation. Wildcard in dom is
-- forbidden by a CHECK constraint here AND by the service layer (defence in
-- depth per CONVENTIONS.md §5 and the phase plan).
--
-- The `casbin_rule` schema follows the canonical Casbin layout so any
-- adapter (pckhoi/casbin-pgx-adapter today, a contingency sqlc adapter
-- tomorrow) can read/write the same rows. tenant_id is NOT a column on
-- casbin_rule — for `p` rows v1 holds the tenant_id; for `g` rows v2 holds
-- it. Applications scope reads by these columns instead of via RLS because
-- Casbin's LoadPolicy does a full-table read on startup.

-- Casbin rule storage.
--   p row: (sub=role_id, dom=tenant_id, obj=resource_type, act=action)
--   g row: (sub=m:<member_id>, role_id, tenant_id)
CREATE TABLE casbin_rule (
    id      bigserial PRIMARY KEY,
    ptype   text NOT NULL,
    v0      text NOT NULL,
    v1      text NOT NULL,
    v2      text,
    v3      text,
    v4      text,
    v5      text,

    -- Layer 6 enforcement: wildcards in domain column forbidden so a buggy
    -- enforcer write can never punch through tenant isolation.
    -- For 'p' rules: v1 is dom; for 'g' rules: v2 is dom.
    CONSTRAINT casbin_rule_no_wildcard_domain_p
        CHECK (ptype <> 'p' OR v1 <> '*'),
    CONSTRAINT casbin_rule_no_wildcard_grouping_dom
        CHECK (ptype <> 'g' OR v2 IS NULL OR v2 <> '*')
);

-- Adapter relies on the index for de-duplication on AddPolicy.
CREATE UNIQUE INDEX casbin_rule_uniq ON casbin_rule (
    ptype,
    v0,
    v1,
    COALESCE(v2, ''),
    COALESCE(v3, ''),
    COALESCE(v4, ''),
    COALESCE(v5, '')
);
CREATE INDEX casbin_rule_ptype_dom_idx ON casbin_rule (ptype, v1);
CREATE INDEX casbin_rule_g_dom_idx     ON casbin_rule (v2)
    WHERE ptype = 'g';

-- Per-tenant role catalogue. casbin_rule references role_ids by name; this
-- table is the human-readable catalogue with metadata, system flag, ETag
-- support, RLS isolation. Roles are tenant-scoped; deleting a role
-- cascades a separate delete of its p-rows via the service layer (the
-- enforcer's RemoveFilteredPolicy keeps casbin_rule consistent).
CREATE TABLE role (
    id              text PRIMARY KEY
                    CHECK (id LIKE 'role\_%' ESCAPE '\'),
    tenant_id       text NOT NULL REFERENCES tenant (id),
    name            text NOT NULL,
    description     text,
    -- System roles are seeded by the tenant.created hook (Phase 8 §8.5)
    -- and refuse delete at the API boundary so an operator can't lock
    -- themselves out by removing tenant_admin.
    is_system       boolean NOT NULL DEFAULT false,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb
                    CHECK (jsonb_typeof(metadata) = 'object'),
    row_seq         bigint NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);

CREATE UNIQUE INDEX role_name_unique
    ON role (tenant_id, name)
    WHERE deleted_at IS NULL;
CREATE INDEX role_tenant_idx
    ON role (tenant_id)
    WHERE deleted_at IS NULL;

CREATE TRIGGER role_bump_row_seq
    BEFORE UPDATE ON role
    FOR EACH ROW EXECUTE FUNCTION bump_row_seq();

ALTER TABLE role ENABLE ROW LEVEL SECURITY;
ALTER TABLE role FORCE  ROW LEVEL SECURITY;
CREATE POLICY role_tenant_only ON role
    USING (tenant_id = current_setting('app.current_tenant_id', true));


-- Permission catalogue. Deployment-wide; not tenant-scoped — every tenant
-- has access to the same permission shape and RBAC determines which roles
-- carry which permissions. Modules document which permissions they
-- consume; this table is the source of truth.
CREATE TABLE permission (
    id              text PRIMARY KEY
                    CHECK (id LIKE 'perm\_%' ESCAPE '\'),
    resource_type   text NOT NULL,
    action          text NOT NULL,
    description     text NOT NULL,
    module          text NOT NULL,
    is_system       boolean NOT NULL DEFAULT true,
    UNIQUE (resource_type, action)
);

-- Seed the MVP permission catalogue. Subsequent phases (API keys, audit)
-- add rows via further migrations with ON CONFLICT DO NOTHING.
INSERT INTO permission (id, resource_type, action, description, module) VALUES
    ('perm_tenant_read',                   'tenant',                'read',        'Read tenant metadata',                          'tenancy'),
    ('perm_tenant_write',                  'tenant',                'write',       'Update tenant',                                 'tenancy'),
    ('perm_tenants_impersonate',           'tenants',               'impersonate', 'Operator impersonation via Acting-Tenant-Id',   'tenancy'),
    ('perm_organization_read',             'organization',          'read',        'Read organizations',                            'organizations'),
    ('perm_organization_write',            'organization',          'write',       'Create / update organizations',                 'organizations'),
    ('perm_organization_delete',           'organization',          'delete',      'Delete organizations',                          'organizations'),
    ('perm_member_read',                   'member',                'read',        'Read members',                                  'organizations'),
    ('perm_member_write',                  'member',                'write',       'Manage members',                                'organizations'),
    ('perm_invitation_read',               'invitation',            'read',        'Read invitations',                              'organizations'),
    ('perm_invitation_write',              'invitation',            'write',       'Create / revoke invitations',                   'organizations'),
    ('perm_user_read',                     'user',                  'read',        'Read users',                                    'identity'),
    ('perm_user_write',                    'user',                  'write',       'Create / update users',                         'identity'),
    ('perm_user_disable',                  'user',                  'disable',     'Disable / enable a user',                       'identity'),
    ('perm_role_read',                     'role',                  'read',        'Read roles',                                    'authorization'),
    ('perm_role_write',                    'role',                  'write',       'Create / update roles',                         'authorization'),
    ('perm_role_delete',                   'role',                  'delete',      'Delete roles',                                  'authorization'),
    ('perm_role_assign',                   'role',                  'assign',      'Assign / unassign roles to members',            'authorization'),
    ('perm_apikey_read',                   'apikey',                'read',        'Read API keys',                                 'apikeys'),
    ('perm_apikey_write',                  'apikey',                'write',       'Manage API keys',                               'apikeys'),
    ('perm_audit_read',                    'audit',                 'read',        'Read audit events',                             'audit'),
    ('perm_notification_read',             'notification',          'read',        'Read notifications',                            'notifications'),
    ('perm_notification_send',             'notification',          'send',        'Send notifications',                            'notifications'),
    ('perm_notification_channel_read',     'notification_channel',  'read',        'Read notification channel config',              'notifications'),
    ('perm_notification_channel_write',    'notification_channel',  'write',       'Manage notification channels',                  'notifications');


-- member_role assignment is a denormalised view of g-rows in casbin_rule
-- carrying metadata (assigned_at, assigned_by) Casbin's row layout cannot
-- hold. The service writes both atomically; the enforcer is the source of
-- truth for runtime checks, this table is the source of truth for the
-- assignment API + audit.
CREATE TABLE member_role (
    member_id    text NOT NULL REFERENCES member (id),
    role_id      text NOT NULL REFERENCES role (id),
    tenant_id    text NOT NULL REFERENCES tenant (id),
    assigned_by  text NOT NULL,
    assigned_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, role_id)
);

CREATE INDEX member_role_tenant_idx ON member_role (tenant_id);
CREATE INDEX member_role_role_idx   ON member_role (role_id);

ALTER TABLE member_role ENABLE ROW LEVEL SECURITY;
ALTER TABLE member_role FORCE  ROW LEVEL SECURITY;
CREATE POLICY member_role_tenant_only ON member_role
    USING (tenant_id = current_setting('app.current_tenant_id', true));


-- Promote member.role_id from text placeholder to real FK. Phase 7 shipped
-- the column as nullable text with no FK because the role table did not
-- exist yet; with the role table now in place we add the constraint
-- in-place — no DROP COLUMN, so no data is lost. Existing rows have
-- role_id NULL (Phase 7 never assigned), which satisfies the FK trivially.
ALTER TABLE member
    ADD CONSTRAINT member_role_id_fkey FOREIGN KEY (role_id) REFERENCES role (id);

CREATE INDEX member_role_id_idx ON member (role_id) WHERE role_id IS NOT NULL;


-- App role grants. Phase 11c tightens to per-Deployment app roles.
GRANT SELECT, INSERT, UPDATE, DELETE ON casbin_rule TO PUBLIC;
GRANT USAGE, SELECT ON SEQUENCE casbin_rule_id_seq TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON role        TO PUBLIC;
GRANT SELECT                         ON permission  TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON member_role TO PUBLIC;
