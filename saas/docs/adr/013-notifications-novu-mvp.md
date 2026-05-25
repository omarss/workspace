# ADR 013 — Promote Notifications module (Novu wrapper) to MVP

## Status

Accepted (2026-05-24, Phase 6).

## Context

The original `AGENTS.md` §15 / §8.7.3 listed Notifications in the v1
roadmap. User feedback (2026-05-24) during Phase 6 planning surfaced
that every other MVP module needs to send transactional email:

- Identity (Phase 5) sends password-reset and email-verify mail.
- Organizations / Members (Phase 7) sends invitation mail.
- Audit (Phase 10) needs notification.* events in the §18.3 list.
- API Keys (Phase 8/9) needs reveal-once + revocation notifications.

Building a stub mailer per module and "swap to Novu later" multiplies
the surface area we have to migrate, all while leaking the same Apache-
2.0 dependency through every consumer. Wrapping Novu from day one is
strictly less work.

## Decision

**Promote Notifications to MVP.** Channels in MVP: `email` (via SMTP /
SendGrid / SES BYOK) and `in_app` (via Novu's built-in channel). SMS,
WhatsApp, push, chat remain v1 roadmap.

The module wraps a self-hosted Novu v3.15.0 stack:

- `ghcr.io/novuhq/novu/api:3.15.0`
- `ghcr.io/novuhq/novu/worker:3.15.0`
- `ghcr.io/novuhq/novu/ws:3.15.0`
- `ghcr.io/novuhq/novu/dashboard:3.15.0` (replaces the legacy `web`
  container in v3)
- `mongo:8.0.17`
- `redis:7-alpine`

Novu's hierarchy is organization → environment → workflow. The platform
maps one Novu environment per Deployment.

The Go adapter is handwritten REST (Novu only publishes a TypeScript
SDK). Surface: trigger workflow, read transaction status, upsert
integration credentials, ensure subscriber.

Channel credentials are BYOK — per-Deployment SMTP / SendGrid / SES
secrets envelope-encrypted via the Phase 4 OpenBao stack. See ADR 017
for the credential-storage details.

Workflow definitions live in Novu's dashboard (port 4000). The platform
DB stores only a `(name, novu_workflow_id)` mapping so platform callers
reference workflows by stable platform-owned names.

## Consequences

### Positive

- One source of truth for all transactional email flows.
- Operators author templates in Novu's UI; no platform-side template
  engine to maintain.
- Re-uses Novu's retry / dedupe / channel-priority logic; we don't
  re-implement the queue.
- Adding a new email provider in v1 is an integration-config change in
  Novu plus a `ChannelProvider` enum extension on our side.

### Negative

- Six new containers in `compose.yaml` (Mongo, Redis, four Novu
  services). Per-Deployment provisioning (Phase 12e) replicates this
  stack.
- Novu owns its own MongoDB — one more storage backend to back up per
  Deployment.
- Novu's `STORE_ENCRYPTION_KEY` must be EXACTLY 32 characters or the
  container boots silently with broken encryption. The `compose.yaml`
  comment + Phase 12e bootstrap script document this loudly.
- Novu v3.15 also requires `STEP_RESOLVER_DISPATCH_URL` on both `novu-api`
  and `novu-worker`; without it the API crash-loops with
  "STEP_RESOLVER_DISPATCH_URL is not defined". Without a dedicated v2
  bridge service, point it at the API itself (`http://novu-api:3000/v1/events`).
  Phase 6 audit captured this; `compose.yaml` carries the same comment.
- Novu's instrumentation bootstrap touches `NEW_RELIC_*` unconditionally;
  set `NEW_RELIC_ENABLED=false` to silence noisy non-fatal init errors.
- A Novu outage breaks password recovery / email verify when
  `NOTIFICATIONS_ENABLED=true`. Mitigation: the Identity service keeps
  the Phase 5 Keycloak-SMTP fallback path; ops can flip the env var to
  cut over.
- Version pin is on v3.15.0 — no separate LTS branch. v3.x rolls forward
  on minors with low self-hoster breakage. Bumping to 3.16.x is a
  single-line `compose.yaml` change; re-verify the env-var set hasn't
  grown.

### Trade-offs intentionally accepted

- Novu Cloud is not used; we self-host to keep PII inside the homelab.
- The Novu `subscriberId` is the platform's `user_id` ULID, not the
  user's email — that way email plaintext never leaves the platform DB
  unless an operator explicitly wires it through a payload variable.

## Anti-patterns (DO NOT)

- DO NOT trigger Novu synchronously from a request handler. The outbox
  worker consumes `notification.queued` events and calls Novu out of
  band so the 202 response is independent of Novu availability.
- DO NOT return channel credentials in any GET / LIST response. The
  OpenAPI schema does not declare a `credentials` field on the response
  — codegen enforces.
- DO NOT widen the workflow shape to accept inline templates from API
  callers. Templates live in Novu; the platform stores only the name →
  id mapping.
- DO NOT hard-code Novu's `JWT_SECRET` / `STORE_ENCRYPTION_KEY` in any
  production overlay. The dev sentinels in `compose.yaml` are clearly
  marked DEV-ONLY; Phase 12e wires per-Deployment values from OpenBao
  KV.

## References

- AGENTS.md §4.4 (open-source matrix — Novu MPL-2.0, network-service),
  §8.7.3 (Notifications deferred → MVP per this ADR), §18.3 (audit
  list), §18.7 (envelope encryption).
- 07-notifications-novu.md (the Phase 6 implementation plan).
- ADR 017 (BYOK credential storage details).
- Novu API reference: <https://docs.novu.co/api-reference>.
- Novu self-host docs: <https://docs.novu.co/self-hosting/deploy-with-docker>.
