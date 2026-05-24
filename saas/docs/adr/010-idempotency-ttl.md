# ADR 010 — Idempotency record TTL and cleanup

## Status

Accepted (2026-05-24, Phase 2).

## Context

AGENTS.md section 5.2 specifies Stripe-style idempotency semantics:

- TTL: 24 hours from first request.
- Same key + same body hash: return the cached response.
- Same key + different body hash: 422 idempotency-key-conflict.
- Same key + concurrent in-flight: second blocks up to 30s; otherwise 409.

The `idempotency_record` table (Phase 2 migration) stores tenant_id,
idempotency_key, route, method, request_body_hash, response_status,
response_headers, response_body, in_flight, created_at, expires_at.

## Decision

- Expiry: `expires_at = created_at + interval '24 hours'`, stamped on first
  `ClaimIdempotencyRecord` call.
- Cleanup: a periodic `DELETE FROM idempotency_record WHERE expires_at <
  now()` query. Phase 2 ships the SQL (`ExpireIdempotencyRecords`); a cron
  / goroutine that calls it lands in Phase 3 once the platform package
  promotion is complete.
- Concurrency: the Phase-2 middleware does not implement the 30s
  block-and-wait behaviour. Concurrent in-flight requests get an immediate
  409 conflict; the contract leaves room to upgrade this to a wait-with-
  backoff in Phase 3 without a spec change.

## Consequences

- The 24-hour window covers ~99% of real client retry windows; longer
  windows would explode storage with little marginal benefit.
- Without the cleanup goroutine the table grows linearly. Phase 3
  cleanup-cron is a hard prerequisite for any production usage.
- Body-hash conflict is a Stripe-style policy decision: same key with a
  different body returns 422 instead of overwriting the cached response.
  This protects clients from accidental key reuse across distinct intents.

## Revisit

Phase 3 promotes the middleware to `internal/platform/idempotency/`; the
cleanup cron lands there. Phase 13+ may add scope-aware idempotency (e.g.
operator impersonation actions get a separate scope) but that is a feature
flag, not a TTL change.
