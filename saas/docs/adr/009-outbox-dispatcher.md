# ADR 009 — In-process outbox dispatcher for MVP

## Status

Accepted (2026-05-24, Phase 2).

## Context

AGENTS.md section 9 mandates the outbox pattern for reliable event publication:
writers insert into an `outbox_event` row in the same transaction as their
state change; a dispatcher polls and publishes.

The dispatcher could be:

1. A separate process (typical at scale; needs orchestration, retries,
   leader election).
2. A goroutine inside the data-plane process (simple; one publisher per
   process; per-Deployment isolation falls out for free).
3. A message broker subscription (NATS, asynq) that consumes outbox rows.

## Decision

Phase 2 ships a single in-process goroutine per data-plane process. It:

- Polls `outbox_event WHERE published_at IS NULL ORDER BY id LIMIT 100`
  every 250 ms.
- Calls the configured `Publisher` per event; on success marks `published_at`,
  on failure increments `delivery_attempts` and records `last_error`.
- Continues on transient errors; does not exit on a single failing event.

The publisher in Phase 2 is `LoggerPublisher` — emits each event via slog.
Real fan-out (webhook delivery, NATS bridge) is deferred to v1.

## Consequences

- One process = one publisher. When we scale the data-plane horizontally
  (post-MVP), the dispatcher needs `SELECT ... FOR UPDATE SKIP LOCKED` plus
  a per-event lease. Phase noted; not implemented in MVP.
- A crashed dataplane leaves unsent events in `outbox_event` until the next
  process restart picks them up — acceptable because the table is durable.
- Pollover latency of ~250 ms is fine for MVP. Tunable via `WithInterval`
  in Phase 3 once the package promotes.
- Phase 2 service methods publish best-effort (publish failure does NOT
  roll back the state change). Phase 3 promotes the EventPublisher onto a
  transactional context so insert + outbox row commit atomically.

## Migration path

- v1: still in-process; add SKIP LOCKED and per-event lease so horizontal
  scaling is safe.
- v2: external worker (Asynq or Watermill) reads `outbox_event` and fans out
  to downstream consumers; legacy LoggerPublisher kept for dev.
- v3: replace polling with `LISTEN/NOTIFY` for near-zero-latency tail.

ADR will be re-opened when the first scale step is needed.
