# ADR 008 — API key argon2id hashing + envelope-encrypted prefix-search index

## Status

Accepted (Phase 9 — 2026-05-25).

## Context

AGENTS.md §8.5 + §18.2 specify the API-key surface (CRUD + rotate + revoke)
and the storage rules: never persist the plaintext secret, hash with
argon2id, never echo the secret after creation. AGENTS.md §18.7 mandates
envelope encryption for any auxiliary index that would allow a DB dump to
correlate prefixes to keys.

Three design constraints inform this ADR:

1. **Constant-time authentication path**. The data-plane bearer-token
   middleware is called on every request. We cannot argon-hash every row in
   the table for every request — we need an O(1) lookup keyed by the
   plaintext prefix, then one argon verify per candidate.
2. **No prefix→key correlation leak from a DB dump**. Storing the plaintext
   prefix in an indexed column lets a snapshot-leak attacker enumerate which
   prefixes exist for which tenants. The envelope-encrypted lookup column
   blinds this without losing the constant-time property.
3. **Rotation must be zero-downtime**. Clients need a grace window during
   which both the old and new bearer authenticate. Per AGENTS.md §8.5 the
   grace defaults to 24 h, max 7 d.

## Decision

### Secret format

Plaintext shown once at create / rotate time:

```text
<env>_<prefix>_<random>
```

- `env` ∈ {`live`, `test`}. Phase 9 only emits `live`; `test` is reserved
  for forward compatibility (per-env quota separation is a v1 roadmap item).
- `prefix` is 8 chars of Crockford base32 from `crypto/rand` (5 bytes →
  8 chars). Stored alongside the row in a plaintext column so dashboards can
  show it to humans for selection.
- `random` is 32 chars of Crockford base32 from `crypto/rand` (20 bytes →
  32 chars). Never persisted in any form except the argon2id PHC hash.

Example: `live_AX9BC7D3_3RKPM8N0DQVE9YJ5T2HZX1WBKFGSHA8C`.

The visible prefix in API responses is `<env>_<prefix>` (11 chars including
the underscore between env and prefix-randomness). The double-underscore
shape lets a casual reader / log line spot `live_*` payloads cheaply.

### argon2id parameters (OWASP 2024)

Hand-rolled PHC string encoding via `golang.org/x/crypto/argon2`, BSD-3 (per
`01-foundations.md` §15). No third-party PHC parser dep — the ~30 LoC
implementation lives in `internal/dataplane/apikeys/argon2.go` and is unit
tested.

```go
const (
    argonTime    uint32 = 2
    argonMemory  uint32 = 19 * 1024   // 19 MiB
    argonThreads uint8  = 1
    argonKeyLen  uint32 = 32
    argonSaltLen        = 16
)
```

PHC format:

```text
$argon2id$v=19$m=19456,t=2,p=1$<b64 salt>$<b64 hash>
```

Salt: 16 random bytes from `crypto/rand` per hash. Verification reparses
the PHC string, re-derives the hash, and constant-time-compares
(`crypto/subtle.ConstantTimeCompare`).

### Envelope-encrypted prefix-search index

Each row carries two prefix-derived columns alongside the plaintext
`prefix`:

1. `prefix_lookup_hash` — HMAC-SHA256(per-deployment HMAC key, prefix).
   Indexed; used as the WHERE clause at auth time. The HMAC key lives in
   OpenBao KV at `secret/data/<deployment_id>/api_keys/prefix_hmac_key`
   and is loaded once per process (cached in-memory).
2. `prefix_lookup_envelope` — envelope-encrypted bundle wrapping the HMAC
   bucket bytes. AAD = `deployment_id|apikey|<api_key_id>|prefix_lookup`
   (CONVENTIONS.md §10.1 format with field-name = `prefix_lookup`). At
   decrypt time the auth path verifies `kid == deployment_id` BEFORE the
   OpenBao round-trip (envelope `ErrKidMismatch` short-circuits cross-
   deployment access — layer 5 of the eight-layer tenant invariant).

Auth-time lookup is:

```text
1. Parse the bearer → extract (env, prefix, random)
2. SELECT * FROM api_key WHERE prefix_lookup_hash = HMAC(prefix)
   AND status IN ('active','rotated')
3. For each candidate row:
   a. Envelope-decrypt prefix_lookup_envelope, verify it matches HMAC(prefix)
      in constant time. Defence in depth — a leak of the HMAC key alone
      cannot forge a lookup without the per-deployment transit key.
   b. argon-verify the FULL bearer against argon_phc.
      If during grace, also try predecessor_argon_phc.
4. First match wins; check revoked_at, expires_at, ip_allowlist.
5. Set principal {actor_type=api_key, actor_id, tenant_id, scopes}.
```

### Rotation with grace period

`POST /v1/api-keys/{id}/rotate` mints a new plaintext secret, moves the
existing `argon_phc` into `predecessor_argon_phc`, sets
`predecessor_expires_at = now() + grace_period_seconds`, and writes the
new `argon_phc`. The prefix changes — the rotation is the point at which
old bearers stop working — but a 24 h-by-default grace lets clients roll
over.

Grace bounds (AGENTS.md §8.5): default 86 400 s, min 0 (immediate cut-
over), max 604 800 s (7 d). Values outside the range are rejected with
422.

A sweeper goroutine clears expired predecessors every hour. The cleanup
is idempotent and fail-soft — a sweep failure is logged but does not
crash the process.

### last_used_at batching

Per-request UPDATE on the API-key row would hot-row the table under load.
The middleware records the (api_key_id, now()) tuple into an in-memory
buffer; a 30-second flush goroutine issues one bulk UPDATE per cycle.
Graceful shutdown forces a final flush so the 30 s window is not lost.

Trade-off: under high contention the visible `last_used_at` can lag the
real last-used time by up to 30 s. Documented in CONVENTIONS.md §6
(Log fields) — operators should not rely on `last_used_at` for sub-minute
freshness.

### RBAC retrofit (Phase 8 pattern)

`POST /v1/tenants/{tenant_id}/api-keys` and
`POST /v1/api-keys/{id}/rotate` are wrapped in
`authorization.EnforceDestructive` with permission `apikey.write`.

The permissions `apikey.read` and `apikey.write` are already in the
catalogue (Phase 8 migration `000006_authorization.up.sql` line 132-133).
`apikey.read` is documented but NOT enforced in MVP — only DESTRUCTIVE
ops go through the retrofit gate per CONVENTIONS.md §2.

## Consequences

### Positive

- Constant-time auth path. One indexed HMAC lookup + at most a small
  handful of argon verifies.
- DB-dump resistant. A snapshot of `api_key` rows alone (without the
  per-deployment HMAC key and transit key) cannot forge a bearer; the
  envelope column adds a second cryptographic barrier on top of argon.
- Per-deployment kid binding integrates with the existing layer-5
  invariant — Phase 4's `envelope.ErrKidMismatch` short-circuit
  applies unchanged.
- Rotation with grace covers the operationally common case (clients
  on autoscaling fleets need a few hours to pick up the new secret).
- No new third-party dep. argon2 is `golang.org/x/crypto/argon2`;
  HMAC + base32 are stdlib.

### Negative

- Per-process HMAC key cache. Rotating the HMAC key requires re-hashing
  every row (deferred — Phase 12+ ops runbook). The argon hash is
  re-computed only on plaintext rotation, not key rotation.
- 19 MiB per argon verify on the auth-time critical path. At 1000 RPS
  the steady-state working set is ~19 GiB — acceptable on the homelab
  host (64 GiB), but documented for capacity planning.
- `last_used_at` lag (≤ 30 s). Acceptable for compliance views; not
  acceptable for security alerting (use the audit log row, not
  `last_used_at`).
- Single-replica rate limiter. Multi-replica path is the same Redis
  watcher ADR 005 calls out for Casbin distribution.

### Alternatives considered

- **Plain b-tree on plaintext prefix**: rejected — a DB dump leaks
  prefix→key correlation immediately.
- **bcrypt or scrypt for the secret hash**: rejected — OWASP 2024
  recommends argon2id for new systems.
- **Single envelope-encrypted column without the HMAC bucket**: rejected
  — auth-time lookup would require decrypting every row.
- **JWT-shaped API keys**: rejected — long-lived JWTs are an
  anti-pattern (no central revocation, large payloads, key rotation
  cascades).

## Related

- AGENTS.md §8.5, §12.6, §17.3, §18.2, §18.7
- ADR 004 — x-pii enforcement pipeline (the AAD + walker conventions
  this ADR builds on)
- ADR 005 — RBAC-with-domains via Casbin (the retrofit gate this ADR
  reuses)
- ADR 006 — OpenBao Shamir + KMS roadmap (the envelope client this ADR
  consumes)
- ADR 010 — Idempotency-Key 24 h TTL (the create/rotate replay path)
- CONVENTIONS.md §2 — service-method signatures + retrofit policy
- CONVENTIONS.md §10.1 — PII / sensitive field envelope conventions
- `docs/plans/mvp/10-api-keys.md` — phase-level decisions
