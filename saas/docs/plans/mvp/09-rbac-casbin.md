# Phase 8 — RBAC-with-Domains on Casbin + pgx Adapter

> **Goal**: Ship the Authorization module: roles, permissions, member-role assignments, and the synchronous `POST /v1/authorization/check` / `/batch-check` endpoint. Use Casbin v2 with the RBAC-with-domains model (`dom = tenant_id`). Forbid wildcard domain via CHECK constraint. Use the pckhoi/casbin-pgx-adapter (after verifying it compiles against casbin v2.135) or fall back to a 80-LoC sqlc adapter. Emit audit events on every assignment and every denial. Wire the §17.3 authorization matrix as the canonical reference for downstream modules.
>
> **Why now**: AGENTS.md §16 puts Authorization after Identity + Organizations because the policy subject `sub` is `member_id`, which only exists after Phase 7. Phase 9 API keys check scopes (which compose with RBAC). Phase 10 Audit emits authorization-denial rows. Every subsequent endpoint in the platform calls `enforcer.Enforce(...)`. Misdesigning this phase forces refactor of every later handler.
>
> **What this phase does NOT do**: No ReBAC / Zanzibar / OpenFGA — pure RBAC per §8.4. No role hierarchy / inheritance beyond Casbin's `g` relation. No just-in-time access (JIT) — out of MVP. No external policy file editing (operators use the API; the model file is shipped in-binary). No multi-replica policy sync (single replica MVP; ADR 005 documents future Redis watcher).
>
> **Maps to AGENTS.md**: §3.6 hexagonal architecture, §8.4 RBAC endpoints, §12.5 Authorization module, §17.3 (matrix mandatory), §18.1 layer 6 (RBAC), §18.3 (audit: role and permission changes). `01-foundations.md` §6 (Casbin model verbatim, enforcer setup, no-wildcard CHECK constraint).
>
> **Estimated subagent sessions**: 3 (one for the adapter compile-check + migration + model file; one for service + handler + assignment endpoints; one for tests + matrix + audit wiring).

---

## Pre-flight

1. AGENTS.md §8.4, §12.5, §17.3, §18.1, §18.3.
2. `01-foundations.md` §6 (verbatim model file + enforcer setup + adapter pin verification mandate).
3. CONVENTIONS.md (Phase 3).
4. Phase 5 (Identity) and Phase 7 (Organizations) — confirm `platform_user`, `member` tables exist with status.
5. **Phase 8 starts with a 30-minute compile-check** before any other coding: `go get github.com/pckhoi/casbin-pgx-adapter/v3@v3.2.0` and verify it builds against `github.com/casbin/casbin/v2@v2.135.0`. If broken, fall back to the contingency adapter (§8.2 below).

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Casbin adapter | pckhoi/casbin-pgx-adapter v3.2.0 (after the compile check) | Thin sqlc-driven adapter implementing `persist.Adapter` (~80 LoC contingency) |
| Watcher (multi-replica policy sync) | None for MVP (single replica). Future: redis-watcher v2.8.0. | Go LISTEN/NOTIFY watcher (does not exist) |
| Policy subject | `member_id` (prefix `m:`) | `user_id` (refused — orgs/multi-tenant); JWT sub direct (refused — couples to KC) |
| Policy domain | `tenant_id` | `organization_id` (refused — most permissions are tenant-wide; org-scoped via metadata if needed later) |
| Wildcard policy | `CHECK (v1 <> '*')` on `casbin_rule` for both `p` and `g` rows | None (refused — wildcard = privilege escalation foothold) |
| Permission split | `obj, act := strings.Cut(permission, ".")` at handler boundary | Single string field in policy (refused — Casbin's `m` matcher prefers split form) |
| Default roles | `role_tenant_admin`, `role_tenant_member`, `role_tenant_billing_admin` (3 seeds per tenant on bootstrap) | None (refused — first PO has to create roles before doing anything) |
| Default permissions | Seeded `permission` table with the union of all module permissions ({tenants, organizations, members, users, api_keys, audit_events, notifications, notification_channels}.{read,write,delete}) | Build on demand (refused — operators don't know what permissions exist) |
| Audit on denial | Yes, every denial emits `authorization.denied` audit row | Sampled (refused — denials are a security signal) |
| Audit on grant change | Yes, `role.created`, `.deleted`, `member_role.assigned`, `.unassigned`, `permission.granted`, `.revoked` | Aggregated daily (refused — audit needs per-event granularity) |

If the user disagrees on any default, stop.

---

## Tasks

### 8.1 Compile-check the adapter (DO THIS FIRST)

```bash
mkdir /tmp/casbin-check && cd /tmp/casbin-check
go mod init check
go get github.com/casbin/casbin/v2@v2.135.0
go get github.com/pckhoi/casbin-pgx-adapter/v3@v3.2.0
cat <<EOF > main.go
package main
import (
    "github.com/casbin/casbin/v2"
    pgxadapter "github.com/pckhoi/casbin-pgx-adapter/v3"
)
func main() { _ = pgxadapter.Adapter{}; _ = casbin.Enforcer{} }
EOF
go build ./...
echo "compile-check result: $?"
```

Expected: exit 0. If non-zero, capture the error and **stop**; switch to the contingency adapter in §8.2.

### 8.2 Contingency adapter (only if §8.1 fails)

Write a minimal sqlc-driven adapter implementing `persist.Adapter`:

```go
package authz

import (
    "context"
    "github.com/casbin/casbin/v2/model"
    "github.com/casbin/casbin/v2/persist"
    "github.com/jackc/pgx/v5/pgxpool"
)

type sqlcAdapter struct{ pool *pgxpool.Pool }

func NewAdapter(pool *pgxpool.Pool) persist.Adapter { return &sqlcAdapter{pool: pool} }

// LoadPolicy reads all rows from casbin_rule and feeds Casbin via
// persist.LoadPolicyLine(line, model).
func (a *sqlcAdapter) LoadPolicy(m model.Model) error { ... }

// SavePolicy is called by EnableAutoSave(false) batch saves. We use
// EnableAutoSave(true) + AddPolicy/RemovePolicy for incremental writes,
// so SavePolicy can be a no-op.
func (a *sqlcAdapter) SavePolicy(m model.Model) error { return nil }

func (a *sqlcAdapter) AddPolicy(sec, ptype string, rule []string) error { ... }
func (a *sqlcAdapter) RemovePolicy(sec, ptype string, rule []string) error { ... }
func (a *sqlcAdapter) RemoveFilteredPolicy(sec, ptype string, fieldIndex int, fieldValues ...string) error { ... }
```

Each method maps to a sqlc query in `internal/dataplane/db/queries/casbin.sql`. The full impl is ~80 LoC; AGENTS.md §3.5 favours this over a stale-looking external dep.

### 8.3 Casbin model file

`internal/dataplane/authorization/rbac.conf` (verbatim from `01-foundations.md` §6):

```ini
[request_definition]
r = sub, dom, obj, act

[policy_definition]
p = sub, dom, obj, act

[role_definition]
g = _, _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub, r.dom) && r.dom == p.dom && r.obj == p.obj && r.act == p.act
```

`go:embed`-ed into the binary so operators can't tamper at runtime.

### 8.4 Migration — `migrations/dataplane/000006_authorization.up.sql`

```sql
-- Casbin policy rows. ptype = 'p' for policies, 'g' for grouping (role assignments).
-- For RBAC-with-domains:
--   p row: (sub=role_id, dom=tenant_id, obj=resource_type, act=action)
--   g row: (sub=member_prefix:member_id, dom=tenant_id, role=role_id)
CREATE TABLE casbin_rule (
    id      bigserial PRIMARY KEY,
    ptype   text NOT NULL,
    v0      text NOT NULL,
    v1      text NOT NULL,
    v2      text,
    v3      text,
    v4      text,
    v5      text,
    -- Wildcard domain forbidden — layer 6 of tenant isolation.
    CONSTRAINT casbin_rule_no_wildcard_domain
        CHECK (ptype <> 'p' OR v1 <> '*'),
    CONSTRAINT casbin_rule_no_wildcard_grouping
        CHECK (ptype <> 'g' OR v2 <> '*')
);
CREATE UNIQUE INDEX casbin_rule_uniq ON casbin_rule (ptype, v0, v1, COALESCE(v2,''), COALESCE(v3,''), COALESCE(v4,''), COALESCE(v5,''));
CREATE INDEX casbin_rule_ptype_dom_idx ON casbin_rule (ptype, v1);   -- v1 = tenant_id

-- Role catalogue (separate from casbin_rule so RBAC API can list roles).
CREATE TABLE role (
    id          text PRIMARY KEY CHECK (id LIKE 'role_%'),
    tenant_id   text NOT NULL REFERENCES tenant (id),
    name        text NOT NULL,
    description text,
    is_system   boolean NOT NULL DEFAULT false,         -- seeded defaults can't be deleted
    row_seq     bigint NOT NULL DEFAULT 1,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    deleted_at  timestamptz,
    UNIQUE (tenant_id, name) WHERE deleted_at IS NULL
);
CREATE TRIGGER role_bump_row_seq BEFORE UPDATE ON role FOR EACH ROW EXECUTE FUNCTION bump_row_seq();
ALTER TABLE role ENABLE ROW LEVEL SECURITY;
ALTER TABLE role FORCE  ROW LEVEL SECURITY;
CREATE POLICY role_tenant_only ON role USING (tenant_id = current_setting('app.current_tenant_id', true));

-- Permission catalogue (deployment-wide; not tenant-scoped — every tenant has access
-- to the same permission shape; RBAC determines who in each tenant gets them).
CREATE TABLE permission (
    id           text PRIMARY KEY CHECK (id LIKE 'perm_%'),
    resource_type text NOT NULL,
    action       text NOT NULL,
    description  text,
    UNIQUE (resource_type, action)
);

-- Seed permissions.
INSERT INTO permission (id, resource_type, action, description) VALUES
    ('perm_tenant_read',     'tenant',     'read',   'Read tenant metadata'),
    ('perm_tenant_write',    'tenant',     'write',  'Update tenant'),
    ('perm_org_read',        'organization','read',  'Read organizations'),
    ('perm_org_write',       'organization','write', 'Create/update organizations'),
    ('perm_org_delete',      'organization','delete','Delete organizations'),
    ('perm_member_read',     'member',     'read',   'Read members'),
    ('perm_member_write',    'member',     'write',  'Invite or remove members'),
    ('perm_user_read',       'user',       'read',   'Read users'),
    ('perm_user_write',      'user',       'write',  'Create/update users'),
    ('perm_user_disable',    'user',       'disable','Disable / enable a user'),
    ('perm_role_read',       'role',       'read',   'Read roles'),
    ('perm_role_write',      'role',       'write',  'Create/update roles'),
    ('perm_role_delete',     'role',       'delete', 'Delete roles'),
    ('perm_role_assign',     'role',       'assign', 'Assign/unassign roles to members'),
    ('perm_apikey_read',     'api_key',    'read',   'List API keys'),
    ('perm_apikey_write',    'api_key',    'write',  'Create/rotate/revoke API keys'),
    ('perm_audit_read',      'audit_event','read',   'Read audit log'),
    ('perm_notification_send', 'notification', 'send', 'Send notifications'),
    ('perm_notification_channel_read',  'notification_channel', 'read',  'Read channel config'),
    ('perm_notification_channel_write', 'notification_channel', 'write', 'Create/update channels'),
    ('perm_tenants_impersonate', 'tenants', 'impersonate', 'Acting-Tenant-Id impersonation (operator-only)');

-- member_role assignment (denormalised view of g-rows in casbin_rule).
-- Carries metadata not present in casbin_rule (assigned_at, assigned_by).
CREATE TABLE member_role (
    member_id   text NOT NULL REFERENCES member (id),
    role_id     text NOT NULL REFERENCES role (id),
    tenant_id   text NOT NULL,
    assigned_by text NOT NULL,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, role_id)
);
ALTER TABLE member_role ENABLE ROW LEVEL SECURITY;
ALTER TABLE member_role FORCE  ROW LEVEL SECURITY;
CREATE POLICY member_role_tenant_only ON member_role USING (tenant_id = current_setting('app.current_tenant_id', true));
```

### 8.5 Seed default roles on tenant create

Update Phase 2's `Tenants.Create` (and the auto-create-default-org hook from Phase 7) to seed three system roles:

```go
type SeedRole struct{ Name string; Description string; Permissions []string }
var defaultRoles = []SeedRole{
    {"tenant_admin", "Full access to the tenant", allPermissions},
    {"tenant_member", "Read access to non-sensitive resources", []string{"perm_tenant_read","perm_org_read","perm_member_read","perm_user_read","perm_audit_read"}},
    {"tenant_billing_admin", "Manage billing (v1)", []string{"perm_tenant_read","perm_audit_read"}},
}
```

For each role: insert into `role`, then insert N casbin_rule rows (one `p` row per (role, resource_type, action) permission).

The bootstrap admin tenant (created during provisioning per §6.2 step 6) also gets an initial member assignment so the operator can call the API.

### 8.6 Module layout — `internal/dataplane/authorization/`

```text
internal/dataplane/authorization/
  rbac.conf
  domain.go          # Role, Permission, MemberRole, CheckRequest, CheckResponse
  ports.go           # RoleRepo, PermissionRepo, MemberRoleRepo, Enforcer (Casbin facade)
  service.go         # listRoles, createRole, deleteRole, assignMemberRole, check, batchCheck
  repo_pgx.go
  enforcer.go        # Casbin enforcer construction + cached load
  handler.go
  errors.go
  service_test.go
  enforcer_test.go
  security_test.go   # §17.3 + RBAC-specific edge cases
```

### 8.7 Enforcer wiring

`internal/dataplane/authorization/enforcer.go`:

```go
package authorization

import (
    "context"
    _ "embed"

    "github.com/casbin/casbin/v2"
    casbinmodel "github.com/casbin/casbin/v2/model"
    pgxadapter "github.com/pckhoi/casbin-pgx-adapter/v3"
    "github.com/jackc/pgx/v5/pgxpool"

    "github.com/omarss/saas/internal/platform/auth"
)

//go:embed rbac.conf
var modelText string

type Enforcer struct{ e *casbin.Enforcer }

func NewEnforcer(ctx context.Context, pool *pgxpool.Pool) (*Enforcer, error) {
    m, err := casbinmodel.NewModelFromString(modelText)
    if err != nil { return nil, err }
    a, err := pgxadapter.NewAdapter(pool, pgxadapter.WithTableName("casbin_rule"), pgxadapter.WithSchema("public"))
    if err != nil { return nil, err }
    e, err := casbin.NewEnforcer(m, a)
    if err != nil { return nil, err }
    e.EnableAutoSave(true)
    if err := e.LoadPolicy(); err != nil { return nil, err }
    return &Enforcer{e: e}, nil
}

// Check returns (allowed, role_that_matched).
func (en *Enforcer) Check(ctx context.Context, memberID, tenantID, resourceType, action string) (bool, string, error) {
    // Member-prefix on subject to keep subjects distinct from roles in g-relation.
    sub := "m:" + memberID
    ok, matched, err := en.e.EnforceEx(sub, tenantID, resourceType, action)
    if err != nil { return false, "", err }
    role := ""
    if ok && len(matched) > 0 && len(matched[0]) > 0 {
        role = matched[0][0]   // p-row's sub column = role_id
    }
    return ok, role, nil
}

func (en *Enforcer) BatchCheck(ctx context.Context, requests []CheckRequest) ([]CheckResponse, error) {
    out := make([]CheckResponse, len(requests))
    for i, r := range requests {
        allowed, role, err := en.Check(ctx, r.MemberID, r.TenantID, r.ResourceType, r.Action)
        if err != nil { return nil, err }
        out[i] = CheckResponse{Allowed: allowed, ViaRole: role}
    }
    return out, nil
}

// AddPolicyP creates a p-row: role can <act> on <obj> in <tenant_id>.
func (en *Enforcer) AddPolicyP(ctx context.Context, roleID, tenantID, obj, act string) error {
    _, err := en.e.AddPolicy(roleID, tenantID, obj, act)
    return err
}

// RemovePolicyP removes a p-row.
func (en *Enforcer) RemovePolicyP(ctx context.Context, roleID, tenantID, obj, act string) error {
    _, err := en.e.RemovePolicy(roleID, tenantID, obj, act)
    return err
}

// AssignMemberRole creates a g-row: member is granted role in tenant.
func (en *Enforcer) AssignMemberRole(ctx context.Context, memberID, roleID, tenantID string) error {
    _, err := en.e.AddGroupingPolicy("m:"+memberID, roleID, tenantID)
    return err
}

func (en *Enforcer) UnassignMemberRole(ctx context.Context, memberID, roleID, tenantID string) error {
    _, err := en.e.RemoveGroupingPolicy("m:"+memberID, roleID, tenantID)
    return err
}
```

### 8.8 OpenAPI — `/v1/tenants/{tenant_id}/roles`, `/v1/permissions`, `/v1/members/{member_id}/roles`, `/v1/authorization/{check,batch-check}`

`openapi/data-plane.yaml` additions:

```yaml
paths:
  /v1/tenants/{tenant_id}/roles:
    parameters: [ { in: path, name: tenant_id, required: true, schema: { type: string } } ]
    get:  { operationId: listRoles, tags: [authorization], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/RoleListResponse" } } } } } }
    post: { operationId: createRole, tags: [authorization], parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ], requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/CreateRoleRequest" } } } }, responses: { "201": { content: { application/json: { schema: { $ref: "#/components/schemas/RoleResponse" } } } } } }

  /v1/roles/{role_id}:
    parameters: [ { in: path, name: role_id, required: true, schema: { type: string, pattern: "^role_[0-9A-HJKMNP-TV-Z]{26}$" } } ]
    get:    { operationId: getRole, tags: [authorization], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/RoleResponse" } } } } } }
    patch:  { operationId: updateRole, tags: [authorization], parameters: [ { $ref: "#/components/parameters/IfMatch" }, { $ref: "#/components/parameters/IdempotencyKey" } ], requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/UpdateRoleRequest" } } } }, responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/RoleResponse" } } } } } }
    delete: { operationId: deleteRole, tags: [authorization], parameters: [ { $ref: "#/components/parameters/IfMatch" } ], responses: { "204": { description: Deleted. } } }

  /v1/permissions:
    get: { operationId: listPermissions, tags: [authorization], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/PermissionListResponse" } } } } } }

  /v1/members/{member_id}/roles:
    parameters: [ { in: path, name: member_id, required: true, schema: { type: string } } ]
    get:  { operationId: listMemberRoles, tags: [authorization], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/MemberRoleListResponse" } } } } } }
    post: { operationId: assignMemberRole, tags: [authorization], parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ], requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/AssignMemberRoleRequest" } } } }, responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/MemberRoleResponse" } } } } } }

  /v1/members/{member_id}/roles/{role_id}:
    parameters: [ { in: path, name: member_id, required: true, schema: { type: string } }, { in: path, name: role_id, required: true, schema: { type: string } } ]
    delete: { operationId: unassignMemberRole, tags: [authorization], responses: { "204": { description: Unassigned. } } }

  /v1/authorization/check:
    post:
      operationId: checkAuthorization
      tags: [authorization]
      requestBody:
        content:
          application/json:
            schema: { $ref: "#/components/schemas/CheckAuthorizationRequest" }
      responses:
        "200": { content: { application/json: { schema: { $ref: "#/components/schemas/CheckAuthorizationResponse" } } } }

  /v1/authorization/batch-check:
    post:
      operationId: batchCheckAuthorization
      tags: [authorization]
      requestBody:
        content:
          application/json:
            schema: { $ref: "#/components/schemas/BatchCheckAuthorizationRequest" }
      responses:
        "200": { content: { application/json: { schema: { $ref: "#/components/schemas/BatchCheckAuthorizationResponse" } } } }

components:
  schemas:
    Role:
      type: object
      required: [id, object, tenant_id, name, is_system, created_at, etag]
      properties:
        id:          { type: string }
        object:      { type: string, enum: [role] }
        tenant_id:   { type: string }
        name:        { type: string }
        description: { type: string }
        is_system:   { type: boolean }
        permissions: { type: array, items: { type: string }, description: "permission_ids granting (resource_type, action) pairs" }
        created_at:  { type: string, format: date-time }
        etag:        { type: string }

    Permission:
      type: object
      required: [id, resource_type, action]
      properties:
        id:            { type: string }
        resource_type: { type: string }
        action:        { type: string }
        description:   { type: string }

    MemberRole:
      type: object
      required: [member_id, role_id, tenant_id, assigned_at, assigned_by]
      properties:
        member_id:   { type: string }
        role_id:     { type: string }
        tenant_id:   { type: string }
        assigned_at: { type: string, format: date-time }
        assigned_by: { type: string }

    CreateRoleRequest:
      type: object
      required: [name]
      properties:
        name:        { type: string }
        description: { type: string }
        permissions: { type: array, items: { type: string } }

    UpdateRoleRequest:
      type: object
      properties:
        name:        { type: string }
        description: { type: string }
        permissions: { type: array, items: { type: string } }

    AssignMemberRoleRequest:
      type: object
      required: [role_id]
      properties:
        role_id: { type: string }

    CheckAuthorizationRequest:
      type: object
      required: [member_id, permission, tenant_id]
      properties:
        member_id:  { type: string }
        permission: { type: string, description: "resource_type.action e.g. invoice.read" }
        tenant_id:  { type: string }

    CheckAuthorizationResponse:
      type: object
      required: [data]
      properties:
        data:
          type: object
          required: [allowed]
          properties:
            allowed:  { type: boolean }
            via_role: { type: [string, "null"] }

    BatchCheckAuthorizationRequest:
      type: object
      required: [checks]
      properties:
        checks: { type: array, maxItems: 100, items: { $ref: "#/components/schemas/CheckAuthorizationRequest" } }

    BatchCheckAuthorizationResponse:
      type: object
      required: [data]
      properties:
        data: { type: array, items: { $ref: "#/components/schemas/CheckAuthorizationResponse" } }
```

### 8.9 Service — `service.go`

The service implements `CheckAuthorization` as:

```go
func (s *Service) Check(ctx context.Context, memberID, permission, tenantID string) (bool, string, error) {
    // 1. Verify caller can ask this question.
    //    Default: caller can check only their own tenant; operators can check any.
    if err := auth.AssertTenant(ctx, tenantID); err != nil { return false, "", err }

    // 2. Split permission at the boundary.
    obj, act, ok := strings.Cut(permission, ".")
    if !ok || obj == "" || act == "" {
        return false, "", ErrMalformedPermission
    }

    // 3. Enforce.
    allowed, via, err := s.enforcer.Check(ctx, memberID, tenantID, obj, act)
    if err != nil { return false, "", err }

    // 4. Audit every denial. Layer 8.
    if !allowed {
        _ = s.events.Publish(ctx, "authorization.denied", tenantID, map[string]any{
            "member_id": memberID, "permission": permission, "tenant_id": tenantID,
            "actor": auth.PrincipalActor(ctx),
        })
    }
    return allowed, via, nil
}
```

`assignMemberRole`:

```go
func (s *Service) AssignMemberRole(ctx context.Context, tenantID, memberID, roleID string) error {
    if err := auth.AssertTenant(ctx, tenantID); err != nil { return err }
    // The caller themselves must have role.assign permission.
    callerMemberID, ok := callerMemberID(ctx)
    if !ok { return auth.ErrUnauthorized }
    allowed, _, _ := s.enforcer.Check(ctx, callerMemberID, tenantID, "role", "assign")
    if !allowed { return auth.ErrMissingScope }

    // Verify member + role exist and belong to tenant (RLS handles this).
    if _, err := s.memberRepo.Get(ctx, tenantID, memberID); err != nil { return err }
    if _, err := s.roleRepo.Get(ctx, tenantID, roleID); err != nil { return err }

    if err := s.enforcer.AssignMemberRole(ctx, memberID, roleID, tenantID); err != nil { return err }
    if _, err := s.memberRoleRepo.Create(ctx, MemberRole{MemberID: memberID, RoleID: roleID, TenantID: tenantID, AssignedBy: callerMemberID}); err != nil {
        // Roll back the casbin g-row to keep mr table + casbin_rule consistent.
        _ = s.enforcer.UnassignMemberRole(ctx, memberID, roleID, tenantID)
        return err
    }

    _ = s.events.Publish(ctx, "member.role_changed", tenantID, map[string]any{
        "member_id": memberID, "role_id": roleID, "operation": "assigned", "assigned_by": callerMemberID,
    })
    return nil
}
```

The `member.role_changed` audit event satisfies §18.3.

### 8.10 Backfill / migration concerns

Phase 7 created members but no role assignments. Phase 8's migration does not assign any roles to existing members — operators must manually grant via the API. To make local dev usable, `make seed-bootstrap-admin` (new target) creates one tenant + one user + one member + assigns `role_tenant_admin` so the operator can call subsequent APIs.

### 8.11 Wire enforcer into existing handlers (gradual)

Phase 7's "any member can invite" TODO is closed here. Update Organizations handler:

```go
func (h *Handler) CreateInvitation(...) {
    p, _ := auth.PrincipalFromContext(ctx)
    allowed, _, _ := h.authz.Check(ctx, callerMember(p), tenantID, "member", "write")
    if !allowed { return problem.Forbidden, nil }
    // ...
}
```

Repeat the pattern across every handler in Phases 2, 5, 6, 7. Each handler now checks Casbin before the service call.

**Trade-off**: this adds one DB read (cached in Casbin's in-memory policy) per request. The Casbin pgx adapter loads policy on startup; `EnableAutoSave(true)` means AddPolicy/RemovePolicy mutate both DB and in-memory state. No per-request DB hit for the check itself.

### 8.12 §17.3 authorization matrix tests

For every endpoint added in this phase AND retrofitted into every prior phase:

| Test | Setup | Assert |
|---|---|---|
| Same-tenant + member with permission | mock JWT with member assigned `tenant_admin` | 200 |
| Same-tenant + member without permission | member assigned `tenant_member` only | 403 |
| Cross-tenant + assigned permission | member in tenant_A; URL targets tenant_B | 403 |
| Operator impersonation | actor_type=operator_impersonation + scope=tenants.impersonate | 200 |
| Operator without impersonation scope | tries Acting-Tenant-Id | 403 |
| Wildcard policy attempted | direct casbin_rule INSERT with v1='*' | DB CHECK rejects |
| Denial emits audit | denied call → outbox event `authorization.denied` exists | matches |
| Batch-check 100 entries | 100-item array | 200; all evaluated |
| Batch-check 101 entries | 101-item array | 422 |
| Permission split malformed | permission="invoice" (no dot) | 422 with `permission-format-invalid` |

### 8.13 ADR 005

`docs/adr/005-rbac-with-domains-casbin.md`:

```markdown
# ADR 005 — RBAC-with-domains on Casbin; dom = tenant_id; no wildcard; no Go LISTEN/NOTIFY watcher

## Status
Accepted (2026-05-24).

## Context
AGENTS.md §8.4 mandates pure RBAC for MVP. We need:
- Per-tenant policy isolation (layer 6 of §18.1).
- Constant-time check (~10µs) on every request.
- An audit trail for grants and denials.
- A path to multi-replica without breaking the model.

Casbin v2's RBAC-with-domains model is the canonical fit:
- `(sub, dom, obj, act)` request
- `g(sub, role, dom)` grouping
- Matcher enforces `dom == p.dom`

The pckhoi/casbin-pgx-adapter v3.2.0 is the only pgx-native adapter; the
upstream casbin/casbin-pg-adapter uses lib/pq (incompatible with our pgx
stack). Last release of the pgx adapter was Aug 2024; verified to build
against casbin v2.135 by the compile-check in Phase 8.1.

## Decision
1. Use Casbin v2.135 + pckhoi/casbin-pgx-adapter v3.2.0.
2. Subject is `m:<member_id>`; domain is `tenant_id`; object is
   `resource_type`; action is `action`.
3. Permission strings split at handler boundary via `strings.Cut(p, ".")`.
4. Wildcard domain forbidden via CHECK constraint on casbin_rule.
5. No Go LISTEN/NOTIFY watcher exists; for MVP we run a single replica.
   Multi-replica path: redis-watcher v2.8.0 (deferred to scale event).
6. Every denial emits `authorization.denied` to the outbox; Phase 10 audit
   consumes.
7. Contingency: if the pgx adapter breaks under casbin upgrades, we ship an
   in-tree sqlc-driven adapter implementing `persist.Adapter` (~80 LoC).

## Consequences
+ Per-tenant isolation enforced at the policy layer; cross-tenant policy
  rows physically can't exist because of CHECK.
+ Permission catalogue lives in the DB; operators see what permissions
  exist.
+ Denials are first-class audit events.
- Cross-tenant queries are impossible by construction — features that
  legitimately need them (operator audit rollup) go through control-plane
  endpoints with a separate role.
- Single replica until scale event. Multi-replica policy sync risk: a
  newly-assigned role takes a moment to propagate across replicas without
  the watcher; tests must not rely on instant visibility.
```

### 8.14 TS SDK + saasctl

`sdk/ts/data-plane/workflows/authorization.ts` exposes `check`, `batchCheck`, `listRoles`, `createRole`, `assignMemberRole`.

`saasctl` adds:

```text
saasctl role list --tenant <id>
saasctl role create --tenant <id> --name <n> --permissions perm_*,perm_*
saasctl role delete <role_id>
saasctl member assign-role <member_id> --role <role_id>
saasctl member unassign-role <member_id> --role <role_id>
saasctl check --member <member_id> --permission resource.action --tenant <id>
```

### 8.15 Commits

```bash
# Verify adapter compile-check first (CRITICAL).
git add internal/dataplane/authorization/rbac.conf
git commit -m "embed casbin model file"

git add migrations/dataplane/000006_authorization.up.sql internal/dataplane/db/queries/casbin.sql
git commit -m "add casbin role permission member_role tables"

git add internal/dataplane/authorization/
git commit -m "implement rbac module with casbin enforcer"

git add internal/dataplane/tenancy/ internal/dataplane/organizations/ internal/dataplane/identity/ internal/dataplane/notifications/
git commit -m "wire enforcer into existing handlers"

git add openapi/data-plane.yaml openapi/problems/
git commit -m "add authorization endpoints to spec"

git add sdk/ts/data-plane/workflows/authorization.ts cmd/saasctl/
git commit -m "ts sdk and saasctl rbac coverage"

git add docs/adr/005-rbac-with-domains-casbin.md
git commit -m "add casbin adr"
```

---

## Verification checklist

```bash
# 1. Adapter compile-check (run BEFORE coding).
$ cd /tmp/casbin-check && go build ./...
# Expected: exit 0. If fails, fall back to contingency adapter.

# 2. Migrations apply.
$ make migrate
$ psql -c "\d casbin_rule" -c "\d role" -c "\d permission" -c "\d member_role"

# 3. Build + lint + tests.
$ make build && make lint && make test && make test-int

# 4. Wildcard domain rejected at DB level.
$ psql -c "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3) VALUES ('p','role_x','*','tenant','read');"
# Expected: ERROR: check constraint "casbin_rule_no_wildcard_domain"

# 5. Default roles seeded per tenant.
$ curl -X POST http://localhost:9090/v1/tenants ... -d '{"slug":"test","name":"Test"}' | jq .data.id
$ curl http://localhost:9090/v1/tenants/<id>/roles ... | jq '.data | map(.name)'
# Expected: ["tenant_admin", "tenant_member", "tenant_billing_admin"]

# 6. Check endpoint.
$ curl -X POST http://localhost:9090/v1/authorization/check ... -d '{"member_id":"<m>","permission":"tenant.read","tenant_id":"<t>"}'
# Expected: { data: { allowed: true, via_role: "role_tenant_member" } }

# 7. Denial audit.
$ curl -X POST http://localhost:9090/v1/authorization/check ... -d '{"member_id":"<m>","permission":"role.delete","tenant_id":"<t>"}'
# Expected: { data: { allowed: false, via_role: null } }
$ psql -c "SELECT type FROM outbox_event WHERE type='authorization.denied' ORDER BY id DESC LIMIT 1;"
# Expected: 1 row

# 8. §17.3 matrix.
$ go test -run TestAuthorization_AuthZ -v ./internal/dataplane/authorization/...

# 9. Assign + unassign role.
$ curl -X POST http://localhost:9090/v1/members/<m>/roles ... -d '{"role_id":"role_..."}'
$ curl -X DELETE http://localhost:9090/v1/members/<m>/roles/<role>

# 10. Existing endpoints now enforce (regression smoke).
$ # Use a member without role.write permission.
$ curl -X POST http://localhost:9090/v1/tenants/<t>/roles ... -d '{"name":"x"}'
# Expected: 403 forbidden
```

---

## Anti-pattern guards

- **NEVER** issue a query that calls `enforcer.Enforce(sub, *, obj, act)` with `*` in any position. The CHECK constraint forbids it; do not bypass.
- **NEVER** read the `dom` from the request body or URL without `AssertTenant`. The dom is the tenant_id from the principal; it must NOT be sourced from caller-provided data unless the caller has `tenants.impersonate`.
- **NEVER** mutate `casbin_rule` directly outside the enforcer. The pgx adapter + autosave keeps in-memory and DB in sync; raw SQL breaks the watcher when it's added.
- **NEVER** add a role permission without going through the service. The DB INSERT path skips the audit emit.
- **NEVER** delete a system role (`is_system=true`). The handler refuses with 422; the only way to remove is via tenant purge.
- **NEVER** split permission strings anywhere except `strings.Cut(p, ".")` at the handler boundary. Re-implementations diverge over time.
- **NEVER** rely on a recently-assigned role being immediately visible across replicas. Single replica today; multi-replica requires the Redis watcher (deferred).
- **NEVER** allow a member of tenant_A to call `/v1/authorization/check` with `tenant_id=tenant_B`. The handler asserts before enforcing.

---

## Open questions

1. **Operator-level "deny override"?** Casbin's policy_effect is `some(where (p.eft == allow))` — pure allow. If an operator needs to forcibly deny something, the only path is to remove permissions. Confirm we don't need deny rules in MVP (§8.4 RBAC is pure allow).
2. **Role permission edits — atomic?** Default: `UpdateRole(permissions: [...])` is a full set-replace inside one transaction (DELETE old p-rows for role, INSERT new). Confirm atomic vs incremental delta.
3. **Permission catalogue evolution.** When Phase 9 adds API key actions, do we add new `permission` rows via migration, or via a runtime call? Default: migration (idempotent INSERT ON CONFLICT DO NOTHING). Phase 9's migration adds api_key permissions.
4. **`role.assign` permission requirement.** Default: AssignMemberRole requires the caller to have `role.assign`. Should the bootstrap admin's first role grant be self-assigning? Default: the bootstrap script inserts the first grant directly (bypasses the enforcer once at setup), then audits a synthetic `bootstrap.role_assigned` event.

---

## Phase 8 — Definition of done

- [ ] Adapter compile-check confirmed (or contingency adapter shipped)
- [ ] Migrations 000006 applied; `casbin_rule`, `role`, `permission`, `member_role` tables exist with RLS + CHECKs
- [ ] Permission catalogue seeded with 21+ rows
- [ ] Default roles (`tenant_admin`, `tenant_member`, `tenant_billing_admin`) auto-created per tenant
- [ ] `internal/dataplane/authorization/` complete: enforcer, service, repo, handler, tests
- [ ] Embedded `rbac.conf` model file
- [ ] Wildcard domain forbidden by DB CHECK; test proves rejection
- [ ] `/v1/authorization/check` and `/batch-check` endpoints E2E
- [ ] Every existing handler retrofitted with `enforcer.Check` before mutation
- [ ] §17.3 matrix tests + RBAC-specific edge cases all pass
- [ ] Denial → `authorization.denied` outbox event
- [ ] TS SDK regenerated + workflow wrapper
- [ ] saasctl `role`, `member assign-role`, `check` subtrees
- [ ] ADR 005 committed
- [ ] All Phase 2-7 tests still green (regression check: every authz test in earlier phases now uses the real enforcer)
- [ ] PR template, `ready` label, CI green

---

End of Phase 8. Next: `10-api-keys.md`.
