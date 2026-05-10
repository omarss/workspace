## Summary
<!-- What changed and why? Include changes the reviewer cannot infer from the diff alone. -->

## Scope
- [ ] API service (`cmd/api`, `internal/api/server`)
- [ ] Item bank (`internal/items`, `db/queries/items.sql`)
- [ ] Auth / sessions (`internal/auth`)
- [ ] Importer (`cmd/importer`)
- [ ] Worker (`cmd/worker`)
- [ ] DB schema / migrations
- [ ] Vendor adapters (`pkg/notifier/*`)
- [ ] Deployment manifests (`homelab/apps/qudrat/`, `homelab/nginx/`)
- [ ] Docs / meta

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
