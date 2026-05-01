# prompter — orientation for Claude

Web game where players write the *shortest* prompt that makes a chosen LLM
reproduce a target output (code first; later: image, video, UI). Score rewards
similarity, brevity, and steering smaller (fewer-parameter) models.

Hosted on this machine: `prompter.omarss.net`, fronted by host nginx, served
out of k3s. Postgres runs on the host (matches the api-mcqs / api-places
pattern).

## Non-negotiables (inherited from workspace conventions)

1. **No Go on host.** All builds, lints, and tests run inside
   `golang:1.26.2-alpine` via `podman` from the Makefile. If you need a tool,
   add it to the builder, not the host.
2. **TDD.** Tests precede code in every package. A package with no `_test.go`
   file does not exist.
3. **No vendor SDK leaks.** App code in `cmd/` and `internal/` MUST NOT import
   third-party LLM/SMS/email SDKs directly. Vendors live behind interfaces in
   `pkg/<name>/<vendor>/` adapters. Swapping providers is a deploy concern.
4. **Latest stable, always.** Verify versions before pinning (web search,
   official release pages). Do not guess.
5. **No emojis** in code, commits, PRs, or content we author.
6. **Atomic commits, lowercase titles, ≤ 50 chars.** Push after each green stage.

## Stack pins (verified 2026-05-01)

| Component | Version | Notes |
|---|---|---|
| Go | 1.26.2 | builder image only |
| PostgreSQL | 18.3 (Percona) | runs on the host, reached via `10.42.0.1` from k3s pods |
| Redis | 8.x | runs in k3s as a Deployment (cache + Asynq queue, no persistent state) |
| chi | v5.2.x | HTTP router |
| sqlc | v1.30.0 | typed queries from SQL |
| migrate | v4.19.0 | golang-migrate, plain SQL up/down |
| Asynq | latest | Redis-backed job queue for grading work |
| Together.ai | — | inference provider for Qwen2.5-Coder family |
| Resend | — | email OTP delivery |
| Twilio Verify | — | SMS OTP |
| Next.js | 15.x | frontend (`web/`) |

## Game model

- **Modalities**: code (Phase 1), image (Phase 3), video (Phase 4), UI (Phase 4).
- **Tier ladder (Phase 1)**: Qwen2.5-Coder-Instruct at 32B / 7B / 3B / 1.5B / 0.5B,
  with multipliers 1.0 / 2.5 / 4.5 / 7.0 / 10.0.
- **Scoring**:
  ```
  score = 1000 × similarity² × tier_multiplier × brevity
  brevity = 1 / (1 + ln(1 + prompt_tokens))
  ```
- **Similarity (code)**: hidden test suite pass-rate (0..1). Each challenge
  ships its own tests; the test runner is the source of truth.
- **Anti-cheat**: reject prompts whose normalized 5-gram overlap with the
  target exceeds 30%. Inference is deterministic (`temperature=0`, fixed seed).
  The cache key is `(prompt, model, seed)`.

## Build flow on this machine

1. `make builder` — build the local builder image once.
2. All Go work runs via `IN_BUILDER` (see Makefile). `make test` / `make lint`
   / `make build` never need Go on the host.
3. Service images: `make image-api`, `make image-worker`. Loaded into k3s
   containerd with `make image-load-<svc>` (uses `sudo k3s ctr images import`).
4. `make k8s-apply` applies the dev overlay into the `prompter` namespace.
5. nginx vhost lives in `homelab/nginx/prompter.omarss.net.conf` (pre-certbot);
   `homelab/Makefile`'s `apply-nginx` target deploys it. Run
   `sudo certbot --nginx -d prompter.omarss.net` once after.

## Layout

```
cmd/<service>/main.go        api, worker
internal/<domain>/...        auth, challenges, grading, inference, leaderboard, store, config
internal/api/server          chi wiring + middleware
pkg/<name>/<vendor>/         vendor adapters (e.g. pkg/llm/together)
api/                         OpenAPI spec (added when contract stabilizes)
db/migrations/               plain SQL up/down
db/queries/                  sqlc input
deploy/k8s/{base,overlays/dev}
build/Containerfile.*
challenges/                  seed JSON/YAML, hand-curated
web/                         Next.js
scripts/
```

## k3s context (single-node)

- Kubernetes 1.34.6+k3s1 on this machine.
- Default storage class: `local-path`.
- Namespace: `prompter`.
- App pods reach host Postgres at `10.42.0.1:5432` via the cni0 gateway.
- nginx proxies `/` → web NodePort, `/api/*` → api NodePort.

## Things that have bitten people here before

- `mkdir` under `sudo` inherits 077 on this machine; use
  `install -d -m 755 -o omar` instead.
- `homelab/Makefile`'s `apply-nginx` clobbers certbot-injected 443 blocks —
  re-run `sudo certbot --nginx -d prompter.omarss.net` after every apply.
- nginx `add_header` does not inherit; any location adding a header drops
  parent headers. Use `snippets/` includes.
- Single-node k3s means no real spread testing — compensate in CI.
