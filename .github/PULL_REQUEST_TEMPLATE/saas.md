## Summary
<!-- What changed and why? Include changes the reviewer cannot infer from the diff alone. -->

## Scope
- [ ] Control plane API (cmd/controlplane, internal/controlplane)
- [ ] Data plane API (cmd/dataplane, internal/dataplane)
- [ ] Platform shared (internal/platform: idempotency, etag, pagination, problem, log, crypto, auth)
- [ ] OpenAPI specs (openapi/)
- [ ] Migrations (migrations/controlplane, migrations/dataplane)
- [ ] Provisioning (deploy/k3s, deploy/nginx, deploy/openbao)
- [ ] SDK (sdk/ts, sdk/go)
- [ ] CLI (cmd/saasctl)
- [ ] Compose / local dev (compose.yaml, Dockerfile.*)
- [ ] CI / lint config
- [ ] Docs / ADRs

## Testing
<!-- Unit, integration against PG, manual curl against the deployed surface. -->

- [ ] `make test` green
- [ ] `make lint` green
- [ ] `make test-int` green (against `make db-up && make migrate-up`)
- [ ] Manual `curl https://qudrat.omarss.net/healthz` (if deployed surface touched)

## Checklist
- [ ] No vendor SDK leaked outside `pkg/<name>/<vendor>/`
- [ ] No secrets, kubeconfigs, or `.env` files committed
- [ ] Arabic text paths normalize per spec §9.1 before hashing/comparison
- [ ] CLAUDE.md / README.md updated if developer-visible behavior changed
- [ ] Tenant isolation invariant honored (see docs/plans/mvp/00-master.md)
