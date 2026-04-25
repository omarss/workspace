## Summary
<!-- What changed and why? Include changes the reviewer cannot infer from the diff alone. -->

## Scope
- [ ] Tenant API
- [ ] Call orchestrator
- [ ] Webhook ingress / delivery
- [ ] Inference services (STT / TTS)
- [ ] Templates / DSL
- [ ] DB schema / migrations
- [ ] Platform abstractions (`pkg/`)
- [ ] Deployment manifests (`deploy/`)
- [ ] Docs / meta

## Testing
<!-- How was this verified? Unit tests, integration tests against k3s, manual call against the dev DID? -->

- [ ] `make test` green
- [ ] `make lint` green
- [ ] Integration tests against PG / NATS / Valkey via testcontainers
- [ ] Manual call exercised end-to-end (if call path touched)

## Checklist
- [ ] No vendor SDK leaked outside `pkg/<name>/<vendor>/`
- [ ] New tenant-scoped tables have RLS policy + migration test
- [ ] No secrets, kubeconfigs, or `.env` files committed
- [ ] OpenAPI spec updated if API surface changed
- [ ] CLAUDE.md / docs updated if developer-visible behavior changed
