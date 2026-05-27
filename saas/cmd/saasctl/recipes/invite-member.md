# Recipe: invite a member

## When to use

You have an Organization (auto-created when a tenant was made) and want
to add a new human member. The invitation flow sends an email via the
Notifications module (ADR 013); the recipient clicks the link, signs
in / signs up via Keycloak, and the membership is created on accept.

## Prerequisites

- Organization ID (`org_…`)
- Caller is an organization-admin or has `members.invite` scope
- A notification channel is configured for the tenant (see
  `configure-notification-channel`) — falls back to the platform
  default SMTP if none is set

## CLI

```text
$ saasctl tenant invite \
    --org org_01HX… \
    --email new.member@acme.test \
    --role member
202 Accepted
{"data":{"id":"inv_01HX…","state":"pending","expires_at":"…"}}
```

## curl

```bash
curl -X POST "https://dev.default.saas.omarss.net/v1/organizations/$ORG_ID/invitations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: idem_$(uuidgen)" \
  -d '{
    "email": "new.member@acme.test",
    "role":  "member"
  }'
```

Response (`202 Accepted`):

```json
{
  "data": {
    "id":         "inv_01HX…",
    "state":      "pending",
    "expires_at": "2026-06-03T12:34:56Z"
  }
}
```

## TS SDK

```typescript
import { OrganizationsApi } from "@omarss/saas-dataplane-sdk";

const orgs = new OrganizationsApi(cfg);
const { data } = await orgs.inviteMember({
  organizationId:    "org_01HX…",
  idempotencyKey:    `idem_${crypto.randomUUID()}`,
  inviteMemberRequest: {
    email: "new.member@acme.test",
    role:  "member",
  },
});
```

## Go SDK

```go
import "github.com/omarss/saas/sdk/go/workflows"

inv, err := workflows.InviteMember(ctx, client, workflows.InviteMemberInput{
    OrganizationID: "org_01HX…",
    Email:          "new.member@acme.test",
    Role:           "member",
})
```

## Common pitfalls

- **Recipient already a member**: returns 409 — list members first.
- **Notification fallback**: if no channel is configured the invitation
  is created but no email is sent; the operator must surface the link
  manually. Watch the audit event `invitation.created` for the URL.
- **TTL**: invitations expire after 7 days. Re-send by deleting and
  re-creating (not by re-issuing the same ID).
