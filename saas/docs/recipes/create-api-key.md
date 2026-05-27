# Recipe: create an API key

## When to use

You want a long-lived credential for a machine client (CI, integration,
internal service). API keys are tenant-scoped, hashed with argon2id, and
indexed by an envelope-encrypted prefix (ADR 008). The secret is shown
ONCE on create — losing it requires `rotate`.

## Prerequisites

- Tenant ID
- Caller has `api_keys.write` permission in that tenant
- Choose a `display_name` for the audit trail

## CLI

```text
$ saasctl api-key create \
    --tenant tenant_01HX… \
    --name   "ci-deploy"
201 Created
{
  "data":   { "id": "api_01HX…", "prefix": "sk_live_AAA…" },
  "secret": "sk_live_AAA…BBBB"
}
```

The full secret is printed once with a "COPY THIS NOW" banner.

## curl

```bash
curl -X POST "https://dev.default.saas.omarss.net/v1/tenants/$TENANT_ID/api-keys" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: idem_$(uuidgen)" \
  -d '{
    "display_name": "ci-deploy",
    "scopes":       ["tenants.read","members.read"]
  }'
```

Response (`201 Created`):

```json
{
  "data": {
    "id":      "api_01HX…",
    "prefix":  "sk_live_AAA…",
    "scopes":  ["tenants.read","members.read"]
  },
  "secret": "sk_live_AAA…BBBB"
}
```

## TS SDK

```typescript
import { ApiKeysApi } from "@omarss/saas-dataplane-sdk";

const keys = new ApiKeysApi(cfg);
const { data: response } = await keys.createApiKey({
  tenantId:       "tenant_01HX…",
  idempotencyKey: `idem_${crypto.randomUUID()}`,
  createApiKeyRequest: {
    display_name: "ci-deploy",
    scopes:       ["tenants.read", "members.read"],
  },
});
console.log("COPY NOW:", response.secret);
```

## Go SDK

```go
import "github.com/omarss/saas/sdk/go/workflows"

result, err := workflows.CreateAPIKey(ctx, client, workflows.CreateAPIKeyInput{
    TenantID:    "tenant_01HX…",
    DisplayName: "ci-deploy",
    Scopes:      []string{"tenants.read", "members.read"},
})
if err != nil { return err }
fmt.Printf("api_key_id=%s secret=%s\n", result.ID, result.Secret)  // print ONCE
```

## Common pitfalls

- **Secret persistence**: store it in your secret manager (OpenBao /
  Vault / 1Password) immediately. The server cannot recover it.
- **Prefix collisions**: the first 8 chars (`sk_live_AAA`) are
  envelope-encrypted to support prefix search without leaking secrets;
  collisions are statistically impossible but show as 422 if observed.
- **Scope wider than caller**: 403 — you cannot grant scopes you do not
  yourself hold.
