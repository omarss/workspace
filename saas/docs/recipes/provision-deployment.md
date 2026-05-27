# Recipe: provision a deployment

## When to use

You are an operator standing up the first (or Nth) SaaS instance. Each
Deployment gets its own k3s namespace, Postgres database, nginx vhost, and
OpenBao transit key. Provisioning takes ~30 s end-to-end and is idempotent
on conflict (a re-run reports the existing Deployment).

## Prerequisites

- Local stack running (`make compose-up` or `saasctl init`)
- Operator bearer token (or local-dev mock headers)
- Operator has `deployments.write` scope

## CLI

```text
$ saasctl deployment create \
    --project default \
    --environment dev \
    --image v0.3.1
Deployment created: dep_01HXAAAAAAAAAAAAAAAAAA
Primary vhost:      https://dev.default.saas.omarss.net
Bootstrap API key:  api_01HXBBBBBBBBBBBBBBBBBB
Bootstrap secret:   sk_live_…   # COPY NOW — shown ONCE
```

## curl

```bash
curl -X POST https://control.saas.omarss.net/control/v1/deployments \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: idem_$(uuidgen)" \
  -d '{
    "project_slug":     "default",
    "environment_slug": "dev",
    "image_version":    "v0.3.1"
  }'
```

Expected `201 Created` body (truncated):

```json
{
  "data": {
    "id": "dep_01HXAA…",
    "state": "active",
    "primary_vhost": "https://dev.default.saas.omarss.net"
  },
  "bootstrap_api_key": {
    "id": "api_01HXBB…",
    "secret": "sk_live_…",
    "tenant_id": "tenant_01HX…"
  }
}
```

## TS SDK

```typescript
import { DeploymentsApi, Configuration } from "@omarss/saas-controlplane-sdk";

const api = new DeploymentsApi(new Configuration({
  basePath: "https://control.saas.omarss.net",
  accessToken: () => operatorToken,
}));

const { data } = await api.createDeployment({
  idempotencyKey: `idem_${crypto.randomUUID()}`,
  createDeploymentRequest: {
    project_slug:     "default",
    environment_slug: "dev",
    image_version:    "v0.3.1",
  },
});
```

## Go SDK

```go
import "github.com/omarss/saas/sdk/go/workflows"

result, err := workflows.ProvisionDeployment(ctx, client, workflows.ProvisionDeploymentInput{
    Project:      "default",
    Environment:  "dev",
    ImageVersion: "v0.3.1",
})
if err != nil {
    return fmt.Errorf("provision: %w", err)
}
fmt.Printf("deployment_id=%s vhost=%s\n", result.DeploymentID, result.PrimaryVhost)
```

## Common pitfalls

- **Idempotency-Key missing**: returns 400 — every write requires one.
- **Bootstrap secret lost**: rotate the API key via
  `POST /v1/api-keys/{id}/rotate`; the original secret is unrecoverable
  by design (argon2id).
- **State stuck on "provisioning"**: check the §6.2 step ledger with
  `saasctl deployment ledger <id>` to identify the failing host adapter.
