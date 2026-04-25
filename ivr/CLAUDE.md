# ivr — orientation for Claude

Multi-tenant conversational IVR platform. v1 scope: inbound + outbound conversational
calls in Arabic and English, AI agent driven by per-tenant templates, signed
webhooks for events, KSA-only PSTN. v2 levers (already shaped in schema, not built):
voice OTP, robo broadcast, global outbound, SMS.

## Non-negotiables

1. **No Go on host.** All builds, lints, and tests run inside `golang:1.26.2-alpine`
   via `podman` from the Makefile. If you need a tool, add it to the builder, not
   the host.
2. **TDD.** Tests precede code in every package. A package with no `_test.go` file
   does not exist.
3. **No vendor SDK leaks.** App code in `cmd/` and `internal/` MUST NOT import
   `cloud.google.com/...`, `github.com/aws/...`, `github.com/Azure/...`. Vendor
   SDKs live only inside `pkg/<name>/<vendor>/` adapters that satisfy our
   interfaces. Swapping clouds is a deploy-time concern.
4. **Multi-tenancy is RLS first.** Every tenant-scoped table has a Postgres RLS
   policy + a migration test that proves cross-tenant reads are denied.
5. **Templates are immutable once published.** A template version is content-addressed.
   Edits create a new version. Calls reference a version, never a name.
6. **Latest stable, always.** Verify versions before pinning (web search, official
   release pages). Do not guess.
7. **No emojis in code, commits, PRs, or templates we author.**
8. **Atomic commits, lowercase titles, ≤ 50 chars.** Push after each green stage.

## Stack pins (verified 2026-04-25)

| Component | Version |
|---|---|
| Go | 1.26.2 |
| PostgreSQL | 18.1-3 (via Percona Operator 2.9.0) |
| NATS JetStream | latest stable |
| Valkey | 8.x |
| SeaweedFS | latest stable |
| Svix Server | latest stable |
| Jambonz | latest stable (verify on bootstrap) |
| Anthropic SDK Go | latest |
| faster-whisper | 1.x (in inference container) |

## Build flow on this machine

1. `podman build` produces images tagged `ivr/<svc>:dev`
2. `podman save | sudo k3s ctr images import -` loads them into k3s containerd
3. Kustomize applies manifests with `imagePullPolicy: Never` for dev overlay
4. No registry needed for dev. CI publishes to a registry separately.

## k3s context (single-node, this laptop)

- Kubernetes 1.34.6+k3s1, control plane on `omar-x1`
- Default storage class: `local-path` (rancher.io/local-path) — single-node hostPath
- GPU: NVIDIA GTX 1050 Ti Mobile, 4 GB VRAM (CUDA 13.0). Fits Piper + small/medium
  faster-whisper at int8. Not enough for local LLMs — Anthropic API stays.
- Namespace for dev: `ivr-dev`. Production lives elsewhere.

## Tests against real infra

- Unit tests: pure Go, run anywhere.
- Integration tests: `testcontainers-go` spawns ephemeral PG, NATS, SeaweedFS,
  Valkey containers via podman. Tag: `//go:build integration`.
- End-to-end tests: against the running k3s `ivr-dev` namespace. Tag:
  `//go:build e2e`. Skip locally unless `IVR_E2E=1`.

## Open architectural levers

- **Recording**: opt-in per template (default off).
- **OTP / robo / SMS**: schema nouns reserved, surfaces deferred to v1.5+.
- **Knowledge / RAG**: pgvector column reserved on `templates`, retrieval
  service deferred to v1.5.
- **KSA SIP carrier**: choice deferred until commercials. Jambonz trunk config
  is a deploy-time concern.

## Things that have bitten people here before

- `mkdir` under `sudo` inherits 077 on this machine; use `install -d -m 755 -o omar`.
- `apply-nginx` from homelab clobbers certbot-injected 443 blocks; not relevant
  to ivr (no nginx vhost yet) but mirror this rule when adding one.
- Single-node k3s means no `topologySpreadConstraints` testing — compensate in CI.
