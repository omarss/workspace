# Recipe: check authorization

## When to use

You want to verify whether a subject can perform an action on a
resource. The endpoint is the same Casbin enforcement loop the
handlers use server-side — useful for client-side UI gating and for
debugging "why was I denied?".

## Prerequisites

- Subject ID (user_id or member_id)
- Action (`read`, `write`, `delete`, …)
- Resource (e.g. `organization:org_01HX…`)

## CLI

```text
$ saasctl auth check \
    --subject  mem_01HX… \
    --action   write \
    --resource organization:org_01HX…
{"data":{"allowed":true,"reason":"role:admin"}}
```

## curl

```bash
curl -X POST https://dev.default.saas.omarss.net/v1/authorization/check \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "subject":  "mem_01HX…",
    "action":   "write",
    "resource": "organization:org_01HX…"
  }'
```

Response:

```json
{
  "data": {
    "allowed": true,
    "reason":  "role:admin grants organization.write"
  }
}
```

For bulk checks call `POST /v1/authorization/batch-check` with an array.

## TS SDK

```typescript
import { AuthorizationApi } from "@omarss/saas-dataplane-sdk";

const auth = new AuthorizationApi(cfg);
const { data } = await auth.check({
  checkRequest: {
    subject:  "mem_01HX…",
    action:   "write",
    resource: "organization:org_01HX…",
  },
});
if (!data.allowed) throw new Error(`denied: ${data.reason}`);
```

## Go SDK

```go
import "github.com/omarss/saas/sdk/go/workflows"

decision, err := workflows.CheckAuthorization(ctx, client, workflows.CheckAuthorizationInput{
    Subject:  "mem_01HX…",
    Action:   "write",
    Resource: "organization:org_01HX…",
})
if !decision.Allowed {
    return fmt.Errorf("denied: %s", decision.Reason)
}
```

## Common pitfalls

- **Idempotency-Key not required**: this is a read; you do NOT need
  `Idempotency-Key`. Most other writes do.
- **Stale tokens**: the JWT carries the subject — refreshing the token
  is required after a role change before the check reflects it.
- **Resource format**: must be `<resource_type>:<resource_id>`; mismatched
  formats silently deny.
