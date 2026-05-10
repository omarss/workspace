# qudrat — orientation for Claude

Assessment-content platform for Saudi Qudurat (Qiyas) and Tahsili
practice. Item bank generation lives in a sibling project (`../questions/`)
and is out of scope here. This service owns: storing items, serving
practice sessions, tracking attempts and mastery, and (later) running
the adaptive engine, leaderboards, mock exams, and analytics calibration.

Hosted on this machine at `qudrat.omarss.net` (later `qudrat.ai`),
fronted by host nginx, served out of k3s. Postgres runs on the host
(matches api-mcqs / api-places / prompter).

## Non-negotiables (inherited from workspace conventions)

1. **No Go on host.** All builds, lints, and tests run inside
   `golang:1.26.2-alpine` via `podman` from the Makefile. If you need a
   tool, add it to the builder, not the host.
2. **TDD.** Tests precede code in every package. A package with no
   `_test.go` file does not exist.
3. **No vendor SDK leaks.** App code in `cmd/` and `internal/` MUST NOT
   import third-party SDKs (Twilio, Resend, Together.ai, etc.) directly.
   Vendors live behind interfaces in `pkg/<name>/<vendor>/` adapters.
4. **Latest stable, always.** Verify versions before pinning. Do not guess.
5. **No emojis** in code, commits, PRs, or content we author.
6. **Atomic commits, lowercase titles, ≤ 50 chars.** Push after each
   green stage.
7. **Arabic content is first-class.** Every text-handling code path must
   normalize Arabic per the spec (strip tatweel, normalize alef/ya/
   ta-marbuta, normalize digits) before hashing or comparing.

## Stack pins (verified 2026-05-09)

| Component | Version | Notes |
|---|---|---|
| Go | 1.26.2 | builder image only |
| PostgreSQL | 18.3 (Percona) | runs on the host, reached via `10.42.0.1` from k3s pods |
| chi | v5.2.x | HTTP router |
| sqlc | v1.30.0 | typed queries from SQL |
| migrate | v4.19.0 | golang-migrate, plain SQL up/down |
| pgx | v5.9.x | Postgres driver |
| Twilio Verify | — | SMS OTP (primary; Saudi students all have phones) |
| Resend | — | Email OTP delivery (fallback) |
| Next.js | 15.x | frontend (`web/`) — Phase 5+ |

## Phase plan

This repo is built phased — see `/home/omar/.claude/plans/gentle-coalescing-parrot.md`
for the full roadmap. Phase 1 ships: scaffold + schema + 245-question
import + healthz, deployable to qudrat.omarss.net but no product features
yet. Phase 2..N add auth, item serving, adaptive engine, frontend,
leaderboards, reviewer pipeline, analytics, billing, parent view.

## Build flow on this machine

1. `make builder` — build the local builder image once.
2. All Go work runs via `IN_BUILDER` (see Makefile). `make test` /
   `make lint` / `make build` never need Go on the host.
3. Service images: `make image-api`, `make image-worker`,
   `make image-importer`. Loaded into k3s containerd with
   `make image-load-<svc>` (uses `sudo k3s ctr images import`).
4. `make k8s-apply` applies the manifests from
   `../../homelab/apps/qudrat/`.
5. nginx vhost lives in `homelab/nginx/qudrat.omarss.net.conf`
   (pre-certbot); `homelab/Makefile`'s `apply-nginx` target deploys it.
   Run `sudo certbot --nginx -d qudrat.omarss.net` once after.

## Layout

```
cmd/<service>/main.go        api, worker, importer
internal/<domain>/...        config, items, attempts, auth (later phases)
internal/api/server          chi wiring + middleware
internal/store               sqlc-generated; checked in
pkg/<name>/<vendor>/         vendor adapters (notifier/twilio, notifier/resend)
db/migrations/               plain SQL up/down
db/queries/                  sqlc input
build/Containerfile.*        api, worker, importer, builder
scripts/                     ad-hoc operator helpers
```

## k3s context (single-node, shared)

- Kubernetes 1.34.6+k3s1 on this machine.
- Default storage class: `local-path`.
- Namespace: `qudrat`.
- App pods reach host Postgres at `10.42.0.1:5432` via the cni0 gateway.
- Host nginx proxies `/` → NodePort `30803`.

## NodePort allocations on this machine

| App        | NodePort |
|------------|---------:|
| api-places |    30801 |
| api-mcqs   |    30802 |
| qudrat     |    30803 |

When adding a new app, take the next free port and document it here.

## Things that have bitten people here before (inherited)

- `mkdir` under `sudo` inherits 077 on this machine; use
  `install -d -m 755 -o omar` instead.
- `homelab/Makefile`'s `apply-nginx` clobbers certbot-injected 443
  blocks — re-run `sudo certbot --nginx -d qudrat.omarss.net` after every
  apply (and similarly for every other previously-issued domain).
- nginx `add_header` does not inherit; any location adding a header
  drops parent headers. Use `snippets/apps-security-headers.conf`.
- Single-node k3s means no real spread testing — compensate in CI.
