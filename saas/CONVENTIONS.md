# CONVENTIONS.md — saas/ module authoring guide

Binding source of truth for how every subsequent module in `internal/` is
shaped. Produced in Phase 3 (`docs/plans/mvp/04-platform-patterns.md`);
approved at CHECKPOINT 1. Subsequent phases mechanically copy the patterns
documented here.

Inherits from:

- `AGENTS.md` — product contract.
- `~/.claude/CLAUDE.md` — global user rules.
- `../CLAUDE.md` — workspace orientation.
- `./CLAUDE.md` — project working notes.

If a section here conflicts with `AGENTS.md`, `AGENTS.md` wins and this
file is updated in the same PR.

---

## 1. Module skeleton

Copy-paste tree for a new domain module under the data plane:

```text
internal/dataplane/<module>/
  domain.go            # types, enums, validation
  ports.go             # Repository + EventPublisher + other ports
  service.go           # orchestration; first non-ctx arg is tenantID for tenant-bound modules
  repo_pgx.go          # pgx-backed Repository implementation
  handler.go           # implements the generated StrictServerInterface entries
  errors.go            # sentinel domain errors translated to RFC 9457 problems
  service_test.go      # unit tests with a mocked Repository
  repo_pgx_test.go     # integration tests via testcontainers-go (build tag `integration`)
  security_test.go     # MANDATORY §17.3 authorization matrix for tenant-bound endpoints
internal/dataplane/db/queries/<module>.sql
migrations/dataplane/<NNNNNN>_<module>.up.sql
openapi/data-plane.yaml                     # add tag + paths + schemas
sdk/ts/data-plane/workflows/<module>.ts     # handwritten wrapper around the generated client
```

Control-plane modules live under `internal/controlplane/<module>/` with the
identical shape minus tenancy concerns (operator context binds
`deployment_id`, not `tenant_id`).

## 2. Service-method signatures

Every method on a tenant-bound service takes `(ctx context.Context,
tenantID string, ...)` as the first two parameters. The compiler enforces
that handlers source `tenantID` from `auth.TenantFromContext` — never from
a request body, URL, query string, or header.

```go
func (s *Service) GetWidget(ctx context.Context, tenantID, widgetID string) (Widget, error) {
    if err := auth.AssertTenant(ctx, tenantID); err != nil {
        return Widget{}, err
    }
    return s.repo.Get(ctx, tenantID, widgetID)
}
```

The Tenants module is the **one exception**: `Service.Create` takes no
`tenantID` because the row being created defines its own tenant id. Every
other module's `Service.Create` MUST take `tenantID` as the first non-ctx
arg.

**Documented exception — Invitation.Accept**: the accept-flow consumes a
state token that ITSELF carries the tenant_id binding (via the invitation
row's `tenant_id` column). The handler does NOT extract tenant_id from JWT
for this single endpoint — it extracts the caller's tenant from JWT, then
**also** verifies the invitation's stored `tenant_id` matches via
`crypto/subtle.ConstantTimeCompare`. The token consumption is the
authentication; the AssertTenant call is replaced by the constant-time
tenant match. See
`internal/dataplane/organizations/invite.go:AcceptInvitation`.

## 3. Handler error mapping

Handlers translate errors with `problem.FromError` — never with raw
`http.Error` or hand-rolled JSON. The catalogue lives in
`internal/platform/problem/types.go` and every constant has a matching
fragment under `openapi/problems/`. Adding a new problem type:

1. Add the URI constant to `types.go`.
2. Add `openapi/problems/<slug>.yaml`.
3. Reference it from the affected response in `openapi/data-plane.yaml`.

Per-error mapping (from `internal/platform/problem/mapper.go`):

| Domain error | Type slug | HTTP |
|---|---|---|
| `auth.ErrUnauthorized` | unauthorized | 401 |
| `auth.ErrCrossTenant` | cross-tenant-access-denied | 403 |
| `auth.ErrMissingScope` | forbidden | 403 |
| `auth.ErrKeyRevoked` | api-key-revoked | 401 |
| `auth.ErrKeyExpired` | api-key-expired | 401 |
| `auth.ErrIPNotAllowed` | ip-not-allowlisted | 403 |
| Module-specific `ErrNotFound` | not-found | 404 |
| Module-specific `ErrETagMismatch` | precondition-failed | 412 |
| Module-specific validation | validation-error | 422 |

## 4. Migrations

Forward-only. Every tenant-bound table:

- Has a `tenant_id text NOT NULL` column with an index on `(tenant_id, ...)`.
- `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`.
- `CREATE POLICY <table>_tenant_only ON <table> USING (tenant_id = current_setting('app.current_tenant_id', true))`.
- `row_seq bigint NOT NULL DEFAULT 1` + the shared `bump_row_seq()`
  trigger for ETag support.

Backward-compatible with the previous image for one release (AGENTS.md §27).
A breaking change requires an ADR + a `/v2` path.

## 5. Tests

Three layers per module — all required for tenant-bound modules:

- `service_test.go` — pure unit tests. Mock the Repository and
  EventPublisher; assert behaviour, validation, event emission.
- `repo_pgx_test.go` — integration via testcontainers-go Postgres. Build
  tag `integration`. Exercises real RLS, the bump_row_seq trigger, etc.
- `security_test.go` — the §17.3 authorization matrix. Mandatory:

| Test name | Setup | Assert |
|---|---|---|
| `TestModule_AuthZ_SameTenant` | mock header tenant == resource owner | 200 |
| `TestModule_AuthZ_CrossTenant` | mock header tenant != resource owner | 403 |
| `TestModule_AuthZ_MissingContext` | no auth | 401 |
| `TestModule_AuthZ_ProdMockRefused` | `SAAS_ENV=prod` + mock header | 401 |
| `TestModule_AuthZ_IgnoresXTenantId` | `X-Tenant-Id` header only | 401 |
| `TestModule_AuthZ_RequiresImpersonateScope` | `X-Acting-Tenant-Id` without scope | 403 |

CI fails the authorization-tests stage if a tenant-bound endpoint lacks
the matrix.

## 6. Log fields

Always emit `{tenant_id, request_id, deployment_id}` on every record. Never
emit `secret`, `password`, `token`, `api_key`, anything in the
`internal/platform/log/redact.go` static keyset, or anything tagged
`pii:"true"` / `sensitive:"true"` in a generated struct. The slog handler
in `internal/platform/log/handler.go` applies the redactor automatically —
do not bypass it.

Adding a new sensitive concept:

1. Add the key to `staticRedactedKeys` in `redact.go`.
2. Add `x-oapi-codegen-extra-tags: { pii: "true" }` (or `sensitive: "true"`)
   to the OpenAPI field so codegen emits the struct tag.
3. The struct walker picks it up automatically.

ADR 004 documents the pipeline.

## 7. Idempotency

Every POST and every state-transition PATCH requires the `Idempotency-Key`
header. The OpenAPI parameter `IdempotencyKey` declares this; the
middleware in `internal/platform/idempotency/` wires:

- Fresh key → handler runs; response cached.
- Same key + same body hash → cached response replayed.
- Same key + different body → 422 `idempotency-key-conflict`.
- Same key + concurrent in-flight → 409 `idempotency-in-flight` (Phase 3
  block-and-wait upgrade lands when needed).

TTL is 24 h (ADR 010). The cleanup ticker runs every 15 min in the
data-plane process.

## 8. ETag

Every mutable resource has `row_seq bigint NOT NULL DEFAULT 1` + the
shared `bump_row_seq()` trigger. The service returns the new `row_seq`;
the handler formats with `etag.Format(seq)`. PATCH / PUT / DELETE clients
echo the value as `If-Match`; mismatch → 412.

## 9. Events

Emit via `EventPublisher.Publish(ctx, eventType, tenantID, payload)`.
Event type follows `<resource>.<verb>` (lowercase, dot-separated):
`tenant.created`, `tenant.updated`, `tenant.suspended`, `tenant.deleted`.
The outbox row is inserted in the same transaction as the state change
once the transactional context promotes (Phase 4+). Phase 3 best-effort
publish is documented in ADR 009.

## 10. PII

Mark in OpenAPI with `x-oapi-codegen-extra-tags: { pii: "true" }` (and
optionally `sensitive: "true"`). Codegen emits `pii:"true"` struct tag.
The slog redactor and the persistence-layer Encryptor walker both honour
it. Phase 4 wires the OpenBao Encryptor; Phase 3 ships the interface +
walker. ADR 004 records the pipeline.

### 10.1 PII persistence convention (Phase 4)

For every field marked `x-oapi-codegen-extra-tags: { pii: "true" }` (or
`sensitive: "true"`):

1. The Go struct carries a sibling `<FieldName>Envelope crypto.Envelope`
   field. The persistence walker populates it; the field is omitted from
   JSON responses (zero-value when the row has no value).
2. The migration adds a five-column set per PII field:

   ```sql
   <field>_ciphertext   bytea NOT NULL
   <field>_wrapped_dek  text  NOT NULL
   <field>_nonce        bytea NOT NULL
   <field>_kid          text  NOT NULL
   <field>_key_version  integer NOT NULL
   ```

3. The repository's `Insert` / `Update` paths call
   **`crypto.EncryptPIIFieldsStrict(ctx, enc, deploymentID, &row)`** (the
   strict variant) immediately before the SQL `INSERT` / `UPDATE`. Strict
   mode errors with `crypto.ErrEnvelopeFieldMissing` if any `pii:"true"`
   / `sensitive:"true"` field lacks a sibling `<Field>Envelope
   crypto.Envelope` field on the struct, so missing siblings fail loudly
   at write time rather than silently dropping PII. The walker reads the
   plaintext, encrypts it, writes the result into `<Field>Envelope`, and
   zeroes the plaintext field on the row.

   The permissive variant `crypto.EncryptPIIFields` is retained for
   backward compatibility but new modules MUST use strict mode. Identity
   (Phase 5) is the first consumer; see
   `internal/dataplane/identity/repo_pgx.go` for the canonical call site
   at `Create` and `Update`.
4. The repository's `Get` path loads the five columns into the sibling
   envelope and calls the matching decrypt helper. The expected kid for
   the decrypt is always the request context's `deployment_id` — the
   helper refuses the call before any OpenBao round-trip if the row's
   `kid` disagrees (`envelope.ErrKidMismatch`). This is layer 5 of the
   eight-layer tenant isolation invariant.
5. The slog redactor handles the in-flight plaintext via the same struct
   tag — no separate registration needed.

AAD (additional authenticated data) for every PII field is

```text
deployment_id || resource_type || resource_id
```

This binds the ciphertext to its row: copying the encrypted blob to a
different row fails the AEAD authentication check. Changing the AAD
format later requires a re-encryption pass over every existing row.

### 10.2 KV v2 secrets (Phase 4)

Per-Deployment secrets (Postgres app password, Keycloak admin creds,
provider API keys, BYOK channel creds) live under

```text
secret/data/<deployment_id>/<purpose>/<name>
```

Use `envelope.Client.KVPut` / `KVGet` / `KVDelete` from
`internal/platform/crypto/envelope`. The helpers reject path traversal
(`..`, leading `/`) at the call-site boundary. The per-Deployment policy
template forbids cross-Deployment KV access at the OpenBao layer, but
the path validation is the first line of defence.

## 11. Cursors

Schema version 1. Every cursor carries `{v, k, id}`; the `v` field is
mandatory. Bumping it returns 410 Gone for old cursors (`cursor-gone`
problem). ADR 011 records the policy. Never silently re-interpret.

## 12. Commit messages

Lowercase, ≤ 50 characters, no Co-Authored-By, no emoji. Examples:

- `promote platform patterns`
- `add idempotency cleanup ticker`
- `wire pgx tenant binding`

Atomic commits per completed feature stage (global CLAUDE.md rule).

## 13. PR template

`.github/PULL_REQUEST_TEMPLATE.md` is the template. Add the `ready` label
once the PR is open so CI runs; monitor and fix any failure. CI billing
may be unavailable in dev — the maintainer notes this in the PR thread
when it applies.

---

## Appendix A — Platform package map

Every cross-cutting helper lives under `internal/platform/`. Reach for
these instead of re-implementing.

| Package | Purpose |
|---|---|
| `auth/` | Principal type, scopes, mock middleware (build-tag-gated), `AssertTenant`, `RequireScope` |
| `tenancy/` | pgx `PrepareConn` hook (`BindOnAcquire`); `MustAcquire` helper that rejects missing-tenant contexts. NOTE: distinct from `dataplane/tenancy/`, which owns the Tenant *resource*. |
| `pgxpool/` | Pool constructor with the standard PrepareConn hook + tracer wiring (`NewPool`, `NewWithTenantBinding` legacy alias) |
| `log/` | slog handler + PII redactor (static keyset + dynamic registration + struct-tag walker) |
| `problem/` | RFC 9457 Problem Details types + `FromError` mapper + catalogue constants |
| `idempotency/` | 24 h Idempotency-Key middleware + pgx Store + cleanup ticker (cleanup wires in cmd/dataplane) |
| `cursor/` | base64url-JSON keyset cursor with mandatory `v` field |
| `pagination/` | `Page[T]` envelope + `ClampLimit` helper |
| `etag/` | Weak ETag formatter (`W/"v<seq>"`) + If-Match parser |
| `id/` | ULID helper with prefix constants (matches AGENTS.md §11.5) |
| `validator/` | go-playground/validator wrapper (skeleton today; v10 wiring lands when first consumer needs it) |
| `outbox/` | In-process Dispatcher + LoggerPublisher + PgxEventPublisher (ADR 009) |
| `otel/` | OpenTelemetry tracer-provider boot (no-op skeleton in Phase 3; OTLP exporter in Phase 15) |
| `crypto/` | Encryptor interface + reflection walker for `pii:"true"` (Phase 3) + EnvelopeAdapter that wraps the OpenBao client (Phase 4) |
| `crypto/envelope/` | OpenBao envelope client (Encrypt / Decrypt with kid binding, EnsureKey, RotateKey, Rewrap, KV v2 helper); k8s + AppRole auth flows (Phase 4) |

## Appendix B — Naming collisions

| Package import path | Owns |
|---|---|
| `internal/platform/tenancy` | the pgx tenant-binding mechanism (BindOnAcquire, MustAcquire). |
| `internal/dataplane/tenancy` | the Tenant *resource* — domain types, service, repository, HTTP handler. |

When both are imported in one file, alias the platform one:

```go
import (
    "github.com/omarss/saas/internal/dataplane/tenancy"
    platformtenancy "github.com/omarss/saas/internal/platform/tenancy"
)
```

## Appendix C — Eight-layer tenant isolation map

Layer responsibility (from `docs/plans/mvp/00-master.md`):

1. **Auth** — `internal/platform/auth/` — JWT/API-key extraction, no header reads.
2. **Service** — first non-ctx arg is `tenantID`; `AssertTenant` precedes any tenant-bound read/write.
3. **DB** — RLS policies on every tenant-bound table; pgx `PrepareConn` sets `app.current_tenant_id`.
4. **Physical** — per-Deployment DB, namespace, vhost (Phase 11+).
5. **Crypto** — per-Deployment transit key; kid bound to deployment_id (Phase 4).
6. **RBAC** — Casbin RBAC-with-domains; `dom = tenant_id` (Phase 8).
7. **Test** — §17.3 matrix mandatory per tenant-bound endpoint.
8. **Audit** — denials emit hashed audit row (Phase 10).

Phase 3 materialises layers 1, 2, 3 (mechanism) and 7 (template); the
remaining layers land in the phases listed.
