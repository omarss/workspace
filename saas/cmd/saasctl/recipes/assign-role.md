# Recipe: assign a role

## When to use

You want to grant a member additional permissions. Roles are bundles of
Casbin policies scoped to a tenant (ADR 005). Phase 8 seeds the default
roles (`owner`, `admin`, `member`) on tenant creation; custom roles are
created via `POST /v1/tenants/{id}/roles`.

## Prerequisites

- Member ID (`mem_…`)
- Role ID (`role_…`) — `saasctl role list --tenant <slug>` enumerates
- Caller has `roles.assign` permission in the same tenant

## CLI

```text
$ saasctl role assign \
    --member mem_01HX… \
    --role   role_01HX…
204 No Content
```

## curl

```bash
curl -X PUT "https://dev.default.saas.omarss.net/v1/members/$MEMBER_ID/roles/$ROLE_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: idem_$(uuidgen)"
```

Response: `204 No Content`.

## TS SDK

```typescript
import { RolesApi } from "@omarss/saas-dataplane-sdk";

const roles = new RolesApi(cfg);
await roles.assignRole({
  memberId:       "mem_01HX…",
  roleId:         "role_01HX…",
  idempotencyKey: `idem_${crypto.randomUUID()}`,
});
```

## Go SDK

```go
import "github.com/omarss/saas/sdk/go/workflows"

err := workflows.AssignRole(ctx, client, workflows.AssignRoleInput{
    MemberID: "mem_01HX…",
    RoleID:   "role_01HX…",
})
```

## Common pitfalls

- **Cross-tenant role**: 403 — roles cannot be assigned across tenants;
  the role and the member must share the same `tenant_id`.
- **Permission cache lag**: authorization decisions are cached for ~30 s
  per pod. To verify immediately, hit
  `POST /v1/authorization/check` (see `check-authorization` recipe) or
  wait for the next polling tick.
- **Removing roles**: `DELETE` the same path returns 204 even when the
  member never had the role — idempotent unassign.
