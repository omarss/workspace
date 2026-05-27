# Recipe: send a notification

## When to use

You want to deliver a transactional message (email / SMS / push) to a
user via the Notifications module (ADR 013). The data plane wraps Novu;
the workflow you reference must already be registered (see
`configure-notification-channel` for setup) and the tenant must have a
default channel mapped or specify one inline.

## Prerequisites

- A notification workflow registered in Novu (e.g. `welcome-email`)
- A channel configured for the tenant (or the platform-default SMTP)
- Recipient identity (user_id, member_id, or `to` block)

## CLI

```text
$ saasctl notification send \
    --workflow welcome-email \
    --to       user_01HX… \
    --payload  '{"display_name":"Acme"}'
202 Accepted
{"data":{"id":"ntf_01HX…","state":"queued"}}
```

## curl

```bash
curl -X POST https://dev.default.saas.omarss.net/v1/notifications/send \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: idem_$(uuidgen)" \
  -d '{
    "workflow_id": "welcome-email",
    "to":          { "user_id": "user_01HX…" },
    "payload":     { "display_name": "Acme" }
  }'
```

Response (`202 Accepted`):

```json
{
  "data": {
    "id":    "ntf_01HX…",
    "state": "queued"
  }
}
```

Poll `GET /v1/notifications/{id}` to track state transitions
(`queued` -> `sent` -> `delivered` / `failed`).

## TS SDK

```typescript
import { NotificationsApi } from "@omarss/saas-dataplane-sdk";

const notifs = new NotificationsApi(cfg);
const { data } = await notifs.sendNotification({
  idempotencyKey: `idem_${crypto.randomUUID()}`,
  sendNotificationRequest: {
    workflow_id: "welcome-email",
    to:          { user_id: "user_01HX…" },
    payload:     { display_name: "Acme" },
  },
});
```

## Go SDK

```go
import "github.com/omarss/saas/sdk/go/workflows"

result, err := workflows.SendNotification(ctx, client, workflows.SendNotificationInput{
    WorkflowID: "welcome-email",
    To:         workflows.NotificationTarget{UserID: "user_01HX…"},
    Payload:    map[string]any{"display_name": "Acme"},
})
```

## Common pitfalls

- **Channel not configured**: 422 `channel_not_configured` — register
  one with `configure-notification-channel`.
- **BYOK credentials rotated**: the provider may return 401; rotate via
  `POST /v1/notification-channels/{id}/rotate-credentials`.
- **Idempotency**: re-using the same key returns the original 202 with
  the existing `ntf_…` id — safe to retry on network blips.
