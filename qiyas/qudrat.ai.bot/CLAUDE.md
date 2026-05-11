# qudrat-bot — orientation for Claude

Telegram + WhatsApp bot for the qudrat practice platform. Each chat user
auto-creates a qudrat user (no signup), picks an interest, and gets an
infinite stream of quiz polls with explanations.

Sibling project to `../qudrat.ai/` — talks to it over HTTP only. No
direct DB access; the API enforces all rules (no-repeat, quota, etc.).

## Non-negotiables

1. **No Go on host.** Builds run inside `golang:1.26.2-alpine` via podman.
2. **No vendor SDKs.** Telegram + Twilio talked to via stdlib `net/http`
   wrappers in `internal/transport/`. Same rule as qudrat.ai.
3. **No emojis** in code, commits, PRs.
4. **Atomic commits, lowercase titles, ≤ 50 chars.**

## Stack pins (verified 2026-05-10)

| Component | Version | Notes |
|---|---|---|
| Go | 1.26.2 | builder image only |
| chi | v5.2.x | webhook router for Twilio inbound |
| Telegram Bot API | — | long-poll (getUpdates) |
| Twilio Conversations | — | webhook for WhatsApp inbound |

## Layout

```
cmd/bot/main.go              wires transports + dispatcher + qudrat client
internal/config              QUDRAT_BOT_* env vars
internal/qudrat              typed client for /api/auth/external + /sessions/* + /attempts
internal/state               in-memory chat ↔ pending poll mapping
internal/transport/telegram  long-poll loop + sendPoll wrapper
internal/transport/whatsapp  Twilio Conversations webhook + button-message wrapper
internal/handler             channel-agnostic dispatcher
internal/server              tiny HTTP server for /healthz + /webhooks/twilio
build/Containerfile.{builder,bot}
scripts/
```

## Deployment

- Pod runs in the `qudrat` namespace alongside `qudrat-api` and `qudrat-web`.
- Talks to qudrat-api via the in-cluster Service:
  `http://qudrat-api.qudrat.svc.cluster.local:8080`.
- Telegram path: outbound only (long-poll), no NodePort needed.
- Twilio path: needs an inbound webhook. `qudrat-bot` exposes 8081 and the
  host nginx proxies `/webhooks/twilio` from `https://qudrat.omarss.net/`
  through to it.

## Things that have bitten us (inherited)

- k3s caches the `:dev` image tag by digest. Always run
  `k3s ctr images rm` before `import` (the redeploy target does this).
