# Recipe: create a tenant

## When to use

You are operating against a live Deployment and want to add a new tenant.
Each tenant is row-level isolated via Postgres RLS plus a `set_config('app.tenant_id', …)` GUC; creating one also seeds a default Organization
so member workflows work immediately.

## Prerequisites

- Data Plane URL for the target Deployment
- Caller bearer token with `tenants.write` permission
- Tenant slug (lowercase, hyphenated) and display name

## CLI

```text
$ saasctl tenant create acme "Acme Inc" --data-plane-url https://dev.default.saas.omarss.net
201 Created
{"data":{"id":"tenant_01HX…","slug":"acme","name":"Acme Inc"}}
```

## curl

```bash
curl -X POST https://dev.default.saas.omarss.net/v1/tenants \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: idem_$(uuidgen)" \
  -d '{"slug":"acme","name":"Acme Inc"}'
```

Expected `201 Created`:

```json
{
  "data": {
    "id":   "tenant_01HX…",
    "slug": "acme",
    "name": "Acme Inc"
  }
}
```

## TS SDK

```typescript
import { TenantsApi, Configuration } from "@omarss/saas-dataplane-sdk";

const tenants = new TenantsApi(new Configuration({
  basePath: dataPlaneURL,
  accessToken: () => userToken,
}));

const { data } = await tenants.createTenant({
  idempotencyKey: `idem_${crypto.randomUUID()}`,
  createTenantRequest: { slug: "acme", name: "Acme Inc" },
});
```

## Go SDK

```go
import "github.com/omarss/saas/sdk/go/workflows"

tenant, err := workflows.CreateTenant(ctx, client, workflows.CreateTenantInput{
    Slug: "acme",
    Name: "Acme Inc",
})
```

## Common pitfalls

- **Slug already taken**: returns 409 — slugs are unique per Deployment.
- **Missing Idempotency-Key**: 400. The header is mandatory on every write.
- **Same Idempotency-Key, different body**: returns 422 with a `body_hash_mismatch` detail — pick a new key when the payload changes.
