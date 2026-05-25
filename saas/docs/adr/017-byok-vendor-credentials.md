# ADR 017 — BYOK vendor credentials: envelope encryption + distinct rotation verb

## Status

Accepted (2026-05-24, Phase 6).

## Context

Per AGENTS.md §18.7 every per-Deployment vendor credential (SMTP
password, SendGrid API key, SES secret access key, future Twilio /
Mailgun keys) is sensitive at rest. The Notifications module is the
first MVP consumer and surfaces the shape every later module
(API Keys, OAuth credentials, webhook signing secrets) will reuse.

Two storage options were considered:

1. **OpenBao KV.** Per-channel secret stored at
   `secret/data/<deployment_id>/notifications/channels/<channel_id>`.
   - Pro: no encryption code on our side; OpenBao manages everything.
   - Con: every notification send hits the KV API to fetch creds before
     calling Novu — a 5-15 ms round-trip on every email send. For
     high-volume tenants this dominates the latency budget.
   - Con: rotation requires double-write into KV + bumping a
     `last_rotated_at` column in Postgres anyway, so it does not avoid
     row-level metadata.

2. **Envelope encryption on the channel row.** Persistence walker
   wraps the plaintext as a DEK + AES-GCM ciphertext stored in five
   columns next to the rest of the row. kid bound to deployment_id.
   - Pro: read-side decrypt is one OpenBao Transit/Decrypt call; no KV
     hop. Cacheable per-channel with short TTL if needed.
   - Pro: rotation is one row write — atomic with bumping `row_seq`
     and stamping `last_rotated_at`.
   - Con: per-DEK cost on every channel insert. Acceptable since
     channels are rare (tens per tenant), not hot.

We picked option 2 — the read path is the hot path, and envelope
encryption matches the existing Phase 4 / Phase 5 pattern (Identity's
Email column uses the same machinery).

The second open question was rotation API shape. Stripe / Square's API
convention is a distinct verb (`POST /resource/{id}/rotate-credentials`)
rather than overloading PATCH. PATCH overloading is a known
anti-pattern: if a metadata edit silently accepts credential fields, an
operator can rotate creds via "fix typo in channel name" — auditors
hate it. We follow Stripe.

## Decision

### 1. Storage shape

Each BYOK row carries one envelope set named after the secret bundle —
e.g. `notification_channel` has

```sql
secrets_ciphertext    bytea       NULLable (NULL for in_app)
secrets_wrapped_dek   text        NULLable
secrets_nonce         bytea       NULLable
secrets_kid           text        NULLable
secrets_key_version   integer     NULLable
```

The Go domain struct declares a sibling

```go
Secrets         string `pii:"true" sensitive:"true"`
SecretsEnvelope crypto.Envelope
```

The strict-mode persistence walker (`crypto.EncryptPIIFieldsStrict`,
introduced in Phase 5) refuses to proceed when the sibling is missing —
a schema bug surfaces as a compile-time / runtime error, not a silent
plaintext write.

### 2. AAD binding

AAD per CONVENTIONS.md §10.1:

```text
deployment_id || resource_type || resource_id
```

Concretely for a notification channel: `dep_X || notification_channel ||
chan_Y`. Copying the encrypted blob to another row fails the AEAD
authentication check. The walker passes the column name (`Secrets`) as
AAD by default; future iterations may switch to the full triple when
the codegen template carries it.

### 3. kid binding

`kid == deployment_id`. Repository hydrate paths assert
`env.KID == r.deploymentID` BEFORE issuing any OpenBao decrypt call.
This is layer 5 of the eight-layer tenant isolation invariant.

### 4. Rotation API

`POST /v1/notification-channels/{channel_id}/rotate-credentials`. Body
carries the new credentials bundle. The endpoint:

1. Validates same-tenant ownership (cross-tenant → 404).
2. Validates the bundle shape for the existing provider.
3. Runs the strict walker on the new plaintext.
4. Issues a single SQL UPDATE that swaps the five envelope columns +
   stamps `last_rotated_at = now()`. `row_seq` increments via the
   shared trigger.
5. Emits `notification_channel.rotated` to the outbox so Phase 10
   audit picks it up.
6. Returns the channel with `credentials_present: true` and the new
   `last_rotated_at` — NEVER the credential bytes.

PATCH on `/v1/notification-channels/{id}` does not accept the
`credentials` field — the OpenAPI schema does not declare it. Codegen
enforces.

### 5. Response shape

GET / LIST never return credential bytes. The `NotificationChannel`
schema declares only `credentials_present: bool` and `last_rotated_at:
date-time | null`. The handler always sets these from the in-memory
struct; the repo clears the plaintext after decrypt so even a buggy
handler cannot stuff the value into the response payload.

### 6. Audit

Per AGENTS.md §18.7 every credential access emits an audit row. Phase 6
emits the outbox event; Phase 10 consumes it into `audit_event`. The
event payload carries `{channel_id, provider, actor_id}` and does NOT
include the credential bytes.

## Consequences

### Positive

- Read-side decrypt is one OpenBao round-trip per send. No KV hop.
- Per-channel rotation without re-encrypting any other row.
- Distinct rotation verb means rotation is auditable in a single
  search of `audit_event WHERE action = 'notification_channel.rotated'`.
- The same shape transfers to future BYOK rows (API key secrets, OAuth
  client secrets, webhook signing secrets) — no new infrastructure
  needed.

### Negative

- One OpenBao Transit/Decrypt per send. For high-volume tenants
  (hundreds of sends/sec) a per-channel decrypt cache with short TTL
  becomes worth adding — out of MVP.
- Rotation is a separate code path from regular updates; operators
  need to know which endpoint to call. Documented in the SDK and the
  Definition of Done checklist.

## Anti-patterns (DO NOT)

- DO NOT add a `credentials` field to `UpdateNotificationChannelRequest`.
  PATCH must remain credential-free.
- DO NOT return `credentials_ciphertext` or any envelope column in any
  API response. Only `credentials_present` + `last_rotated_at`.
- DO NOT call `OpenBao Transit/Decrypt` on a channel row before
  asserting `secrets_kid == deployment_id`. The hydrate path must
  fail-closed with `envelope.ErrKidMismatch` before reaching the
  decrypt call.
- DO NOT log channel decrypt outcomes that include any portion of the
  plaintext. The slog redactor already covers the `Secrets` field via
  its `pii:"true"` tag, but error messages must not be hand-rolled to
  bypass it.
- DO NOT skip the rotation audit emit. §18.7 makes it mandatory.

## References

- AGENTS.md §18.7 (envelope encryption + key binding rules).
- CONVENTIONS.md §10.1 (the persistence walker + AAD format).
- ADR 004 (x-pii enforcement + codegen pipeline).
- ADR 006 (OpenBao Shamir + KMS roadmap).
- ADR 013 (Notifications promoted to MVP — uses this storage shape).
- Stripe API rotation pattern: <https://stripe.com/docs/keys#rolling-keys>.
