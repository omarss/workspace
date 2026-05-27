# Recipe: view audit events

## When to use

You are investigating an incident, satisfying a compliance request, or
checking who did what. Every security-sensitive action emits an audit
event (ADR 012) into a hash-chained, append-only table. The export
endpoint streams JCS-canonicalised JSON suitable for offline verify.

## Prerequisites

- Tenant ID (data plane scope)
- Caller has `audit.read` permission

## CLI

```text
$ saasctl audit list \
    --tenant tenant_01HX… \
    --since  2026-05-20T00:00:00Z \
    --limit  20
{
  "data": [
    {
      "id":      "audit_01HX…",
      "actor":   "user_01HX…",
      "action":  "tenant.create",
      "target":  "tenant:tenant_01HX…",
      "at":      "2026-05-26T10:11:12Z",
      "prev":    "blake3:…",
      "self":    "blake3:…"
    }
  ],
  "next_cursor": "v1:…"
}
```

## curl

```bash
curl -G "https://dev.default.saas.omarss.net/v1/tenants/$TENANT_ID/audit-events" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "since=2026-05-20T00:00:00Z" \
  --data-urlencode "limit=20"
```

Use `?cursor=v1:…` to paginate forward. Cursors are versioned (ADR 011);
an old cursor returns `410 Gone`, not a silent re-interpretation.

For an integrity verification:

```bash
curl -X POST "https://control.saas.omarss.net/control/v1/deployments/$DEP_ID/audit-integrity" \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -H "Idempotency-Key: idem_$(uuidgen)"
```

The control plane re-derives every hash and reports the first divergence.

## TS SDK

```typescript
import { AuditApi } from "@omarss/saas-dataplane-sdk";

const audit = new AuditApi(cfg);
const { data } = await audit.listAuditEvents({
  tenantId: "tenant_01HX…",
  since:    "2026-05-20T00:00:00Z",
  limit:    20,
});
for (const ev of data.data) console.log(ev.action, ev.at, ev.actor);
```

## Go SDK

```go
import "github.com/omarss/saas/sdk/go/workflows"

events, err := workflows.ListAuditEvents(ctx, client, workflows.ListAuditEventsInput{
    TenantID: "tenant_01HX…",
    Since:    "2026-05-20T00:00:00Z",
    Limit:    20,
})
```

## Common pitfalls

- **No UPDATE / DELETE grant**: the app role has no UPDATE / DELETE on
  `audit_event`. Tests that need a clean state must rebuild the DB.
- **Hash chain breaks**: an integrity break means tampering; do NOT
  truncate the table — capture a forensic dump and rotate keys.
- **Time-window queries**: `since` must be RFC3339; epochs are 400.
