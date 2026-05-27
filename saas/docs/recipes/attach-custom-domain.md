# Recipe: attach a custom domain

## When to use

A tenant wants to serve their Deployment from their own domain (BYOD).
ADR 015 covers the DNS-TXT proof flow: attach, wait for the operator
(or end-user) to publish the verification record, verify, then
Certbot issues the public cert on the host nginx.

## Prerequisites

- Deployment ID (`dep_…`)
- Operator with `deployments.write` scope
- The custom domain's DNS is controllable by the requesting party

## CLI

```text
$ saasctl domain attach dep_01HX… --domain app.acme.test
201 Created
{
  "data": {
    "id":      "dom_01HX…",
    "state":   "pending_verification",
    "txt_record": {
      "name":  "_saas-verify.app.acme.test",
      "value": "saas-verify=abc123def456…"
    }
  }
}
```

Publish the TXT record on the customer's authoritative DNS, then:

```text
$ saasctl domain verify dep_01HX… --domain-id dom_01HX…
{"data":{"state":"verified","cert_issued_at":"…"}}
```

## curl

```bash
# 1. Attach
curl -X POST "https://control.saas.omarss.net/control/v1/deployments/$DEP_ID/domains" \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: idem_$(uuidgen)" \
  -d '{"domain":"app.acme.test"}'

# 2. Publish TXT on customer DNS (out-of-band).

# 3. Verify
curl -X POST "https://control.saas.omarss.net/control/v1/deployments/$DEP_ID/domains/$DOMAIN_ID/verify" \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -H "Idempotency-Key: idem_$(uuidgen)"
```

## TS SDK

```typescript
import { DomainsApi } from "@omarss/saas-controlplane-sdk";

const dom = new DomainsApi(cfg);
const { data: pending } = await dom.attachDomain({
  deploymentId:   "dep_01HX…",
  idempotencyKey: `idem_${crypto.randomUUID()}`,
  attachDomainRequest: { domain: "app.acme.test" },
});
// publish pending.data.txt_record on the customer's DNS, then:
await dom.verifyDomain({
  deploymentId:   "dep_01HX…",
  domainId:       pending.data.id,
  idempotencyKey: `idem_${crypto.randomUUID()}`,
});
```

## Go SDK

```go
import "github.com/omarss/saas/sdk/go/workflows"

// Single-call wrapper that polls DNS + verifies once the TXT is live.
result, err := workflows.AttachCustomDomain(ctx, client, workflows.AttachCustomDomainInput{
    DeploymentID: "dep_01HX…",
    Domain:       "app.acme.test",
    WaitForDNS:   true,
    PollInterval: 15 * time.Second,
    Timeout:      10 * time.Minute,
})
```

## Common pitfalls

- **Wildcard certificates**: not supported in MVP — one cert per FQDN.
- **TXT record not propagated**: the verify endpoint retries DNS for up
  to 30 s before returning 422. Use `dig +short TXT _saas-verify…` to
  confirm propagation before calling verify.
- **`apply-nginx` clobbers certbot**: after the verify step, the
  control plane re-renders the per-Deployment vhost and runs
  `nginx -s reload` directly — it does NOT call homelab's
  `make apply-nginx` (which would wipe the certbot 443 block).
