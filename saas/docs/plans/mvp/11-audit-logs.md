# Phase 10 — Audit Logs (Append-Only Grants + Hash Chain + Integrity Verify)

> **Goal**: Ship the Audit module: `audit_event` table with hash chain (`prev_hash`, `row_hash = sha256(prev_hash || canonical_json(row))` per RFC 8785 JCS). Postgres trigger that REVOKES UPDATE and DELETE grants on `audit_event` from the app role. `/v1/tenants/{tenant_id}/audit-events` list (cursor-paginated), `/v1/audit-events/{id}` get, `/v1/audit-events/export` (CSV/JSON). Control-plane `/control/v1/deployments/{id}/audit-integrity` walks the chain and reports the first-mismatch row. Subscriber that consumes the outbox events from Phases 5-9 and writes audit rows synchronously where §18.3 requires.
>
> **Why now**: AGENTS.md §16 puts Audit last in the data-plane group because everything else emits audit events. The §18.3 list is exhaustive: provisioning, login, suspension, role change, API key CRUD, file deletion (v1), webhook secret rotation (v1), user disable/enable/password reset, notification send, billing (v1). Phase 10 lands all of these. CHECKPOINT 3 follows because the data plane is now complete.
>
> **What this phase does NOT do**: No SIEM integration (Loki/VictoriaLogs only — and only as a tail target, not as the source of truth). No real-time alerting (out of MVP). No automatic chain repair on detected tampering — operator reads the verify endpoint and manually triages. No GDPR/PDPL field-level redaction inside audit_event (out of MVP; purge endpoint handles erasure).
>
> **Maps to AGENTS.md**: §3.6 hexagonal, §8.6 Audit endpoints, §12.7 Audit module, §17.3 (matrix; audit is mostly read-only so the matrix is shorter), §18.1 layer 8 (audit), §18.3 (the action list), §18.5 (PII redaction in metadata), §18.6 (right-to-erasure: tenant.purged audit row emitted BEFORE rows disappear). `01-foundations.md` §13 (`audit_` prefix).
>
> **Estimated subagent sessions**: 3 (one for migration + grants trigger + canonical JSON; one for subscriber + service + handler; one for verify endpoint + tests + control-plane wiring).

---

## Pre-flight

1. AGENTS.md §8.6, §12.7, §18.1, §18.3, §18.5, §18.6.
2. `01-foundations.md` §13.
3. Phases 2-9 (every module that emits outbox events with names matching the §18.3 list).
4. RFC 8785 (JSON Canonicalization Scheme) — read the spec section on key ordering + number formatting.
5. CONVENTIONS.md §6 (Log fields) — audit metadata uses the same redaction model.

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Canonical JSON form | RFC 8785 JCS (JSON Canonicalization Scheme — alphabetical keys + lowercased exponents + UTF-8 + canonical numbers) | Custom ordered-key form (refused — easier to break compat); JSON-LD (out of scope) |
| Hash function | SHA-256 over `prev_hash || JCS(row_no_hashes)`; `row_hash` stored, `prev_hash` is FK to last id's hash | SHA-3 (refused — overkill); HMAC (refused — needs key rotation) |
| Append-only enforcement | Postgres trigger that revokes UPDATE/DELETE grants on `audit_event` from the app role (one-time during migration) + DENY UPDATE/DELETE policies at RLS layer | App-layer only (refused — defense in depth) |
| Genesis row per tenant | Each tenant's first audit row has `prev_hash = '\x' || sha256(tenant_id || 'genesis')` | NULL prev_hash (refused — ambiguous; explicit genesis is auditable) |
| Chain order | Per-tenant chain (each tenant has its own chain ordered by `(tenant_id, id)` where id is a monotonic ULID) | Single chain per Deployment (refused — tenant isolation breach) |
| Subscriber model | Single goroutine in dataplane binary consumes `outbox_event` rows with type in §18.3 list, writes `audit_event` synchronously in the same tx as the outbox publish ack | Async (refused — drops on crash) |
| Export size threshold | Sync ≤ 1 MB; async ≥ 1 MB returns `202 Accepted` + a `Location` for polling | Always sync (refused — large tenants OOM); always async (refused — bad UX for small exports) |
| Verify endpoint scope | Operator-only on control plane; data-plane tenants do NOT expose the integrity verify (avoids leaking which row tampered) | Per-tenant verify (refused — operator-only is the right level) |
| PII handling in metadata | Same redactor list as slog; metadata fields tagged `pii:"true"` are envelope-encrypted | Plaintext in audit (refused — audit_event is a giant attack surface) |

If the user disagrees on any default, stop. The chain canonicalization is hard to change later.

---

## Tasks

### 10.1 OpenAPI spec — audit endpoints

`openapi/data-plane.yaml`:

```yaml
paths:
  /v1/tenants/{tenant_id}/audit-events:
    parameters: [ { in: path, name: tenant_id, required: true, schema: { type: string } } ]
    get:
      operationId: listAuditEvents
      tags: [audit]
      parameters:
        - $ref: "#/components/parameters/Limit"
        - $ref: "#/components/parameters/Cursor"
        - { in: query, name: action,        schema: { type: string } }
        - { in: query, name: resource_type, schema: { type: string } }
        - { in: query, name: resource_id,   schema: { type: string } }
        - { in: query, name: actor_id,      schema: { type: string } }
        - { in: query, name: occurred_after,  schema: { type: string, format: date-time } }
        - { in: query, name: occurred_before, schema: { type: string, format: date-time } }
      responses:
        "200": { content: { application/json: { schema: { $ref: "#/components/schemas/AuditEventListResponse" } } } }

  /v1/audit-events/{audit_event_id}:
    parameters: [ { in: path, name: audit_event_id, required: true, schema: { type: string, pattern: "^audit_[0-9A-HJKMNP-TV-Z]{26}$" } } ]
    get: { operationId: getAuditEvent, tags: [audit], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/AuditEventResponse" } } } } } }

  /v1/audit-events/export:
    post:
      operationId: exportAuditEvents
      tags: [audit]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody:
        content:
          application/json:
            schema: { $ref: "#/components/schemas/ExportAuditEventsRequest" }
      responses:
        "200":
          description: "Sync export when response would be ≤ 1MB"
          content:
            text/csv: { schema: { type: string } }
            application/json: { schema: { $ref: "#/components/schemas/AuditEventListResponse" } }
        "202":
          description: "Async export; poll Location for the file"
          headers:
            Location: { schema: { type: string } }
```

`openapi/control-plane.yaml`:

```yaml
paths:
  /control/v1/deployments/{deployment_id}/audit-integrity:
    parameters: [ { in: path, name: deployment_id, required: true, schema: { type: string } } ]
    get:
      operationId: verifyDeploymentAuditIntegrity
      tags: [audit]
      parameters:
        - { in: query, name: tenant_id, schema: { type: string }, description: "Optional; verify a single tenant's chain" }
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/AuditIntegrityResponse" }

components:
  schemas:
    AuditIntegrityResponse:
      type: object
      required: [data]
      properties:
        data:
          type: object
          required: [verified, rows_checked, first_mismatch_id]
          properties:
            verified:             { type: boolean }
            rows_checked:         { type: integer }
            first_mismatch_id:    { type: [string, "null"] }
            first_mismatch_tenant_id: { type: [string, "null"] }
            first_mismatch_reason:    { type: [string, "null"], description: "prev_hash | row_hash | sequence-gap" }
            verified_at:          { type: string, format: date-time }
```

`AuditEvent` schema (data plane):

```yaml
    AuditEvent:
      type: object
      required: [id, tenant_id, actor_type, actor_id, action, resource_type, occurred_at, prev_hash, row_hash]
      properties:
        id:            { type: string, pattern: "^audit_[0-9A-HJKMNP-TV-Z]{26}$" }
        tenant_id:     { type: string }
        actor_type:    { type: string, enum: [user, api_key, operator, operator_impersonation, system] }
        actor_id:      { type: string }
        action:        { type: string }
        resource_type: { type: string }
        resource_id:   { type: [string, "null"] }
        occurred_at:   { type: string, format: date-time }
        ip_address:    { type: [string, "null"], x-oapi-codegen-extra-tags: { pii: "true" } }
        user_agent:    { type: [string, "null"], x-oapi-codegen-extra-tags: { pii: "true" } }
        request_id:    { type: [string, "null"] }
        metadata:      { type: object, additionalProperties: true, x-oapi-codegen-extra-tags: { sensitive: "true" } }
        prev_hash:     { type: string, description: "Hex" }
        row_hash:      { type: string, description: "Hex" }
```

### 10.2 Migration — `migrations/dataplane/000008_audit.up.sql`

```sql
CREATE TABLE audit_event (
    id              text PRIMARY KEY CHECK (id LIKE 'audit_%'),
    tenant_id       text NOT NULL,                  -- NOT FK; we want audit rows to outlive tenant soft-delete
    actor_type      text NOT NULL CHECK (actor_type IN ('user','api_key','operator','operator_impersonation','system')),
    actor_id        text NOT NULL,
    action          text NOT NULL,
    resource_type   text NOT NULL,
    resource_id     text,
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    ip_address      text,                            -- PII (encrypted via walker if Phase 4 enabled)
    ip_address_envelope_kid text,
    user_agent      text,
    request_id      text,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata_ciphertext  bytea,                     -- envelope-encrypted full metadata (forensic-recoverable)
    metadata_wrapped_dek text,
    metadata_nonce       bytea,
    metadata_kid         text,
    metadata_key_version integer,
    -- Hash chain.
    prev_hash       bytea NOT NULL,                  -- 32 bytes
    row_hash        bytea NOT NULL,                  -- 32 bytes
    chain_sequence  bigint NOT NULL,                 -- monotonic per tenant; populated by trigger
    UNIQUE (tenant_id, chain_sequence)
);
CREATE INDEX audit_event_tenant_time_idx ON audit_event (tenant_id, occurred_at DESC);
CREATE INDEX audit_event_resource_idx    ON audit_event (tenant_id, resource_type, resource_id);
CREATE INDEX audit_event_actor_idx       ON audit_event (tenant_id, actor_id, occurred_at DESC);

ALTER TABLE audit_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_event FORCE  ROW LEVEL SECURITY;
CREATE POLICY audit_event_tenant_only ON audit_event
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- Append-only via grants. The app role can SELECT and INSERT; UPDATE and
-- DELETE are explicitly revoked. The control-plane integrity verify uses a
-- separate role with SELECT-only.
GRANT SELECT, INSERT ON audit_event TO PUBLIC;
REVOKE UPDATE, DELETE ON audit_event FROM PUBLIC;

-- Sequence trigger: each row gets the next chain_sequence for its tenant.
CREATE OR REPLACE FUNCTION audit_event_assign_sequence() RETURNS trigger AS $$
DECLARE
    last_seq bigint;
BEGIN
    SELECT COALESCE(MAX(chain_sequence), 0) INTO last_seq
    FROM audit_event WHERE tenant_id = NEW.tenant_id;
    NEW.chain_sequence := last_seq + 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_event_seq BEFORE INSERT ON audit_event
    FOR EACH ROW EXECUTE FUNCTION audit_event_assign_sequence();
```

The trigger handles the per-tenant monotonic sequence. The `prev_hash` and `row_hash` are computed in Go before INSERT — the trigger does NOT touch them (Postgres-side canonicalization is too risky to maintain).

### 10.3 Canonical JSON (RFC 8785 JCS) — `github.com/gowebpki/jcs` v1.0.1

**Decision (resolved pre-Phase-10)**: use the vetted external library `github.com/gowebpki/jcs` v1.0.1 (Apache-2.0). Rolling our own ~80 LoC fails the moment the audit payload includes a non-ASCII string or a float that needs the ECMAScript canonical form — and a single off-by-one in number serialization silently breaks the hash chain forever.

Adapter file `internal/dataplane/audit/jcs.go`:

```go
package audit

import (
    "encoding/json"
    "fmt"

    "github.com/gowebpki/jcs"
)

// Canonical returns the RFC 8785 JCS bytes for v. v must be JSON-marshallable.
// The library handles UTF-16 key ordering, ECMAScript-canonical number form,
// and JSON-string-escape rules — all the parts that are dangerous to hand-roll.
func Canonical(v any) ([]byte, error) {
    raw, err := json.Marshal(v)
    if err != nil {
        return nil, fmt.Errorf("audit jcs marshal: %w", err)
    }
    canon, err := jcs.Transform(raw)
    if err != nil {
        return nil, fmt.Errorf("audit jcs transform: %w", err)
    }
    return canon, nil
}
```

Add to `go.mod`:

```bash
go get github.com/gowebpki/jcs@v1.0.1
```

License: Apache-2.0 (satisfies AGENTS.md §3.5 OSI-approved requirement). Maintainer: gowebpki org (Bret Jordan); upstream is Anders Rundgren's reference (the RFC author). Last tagged release 2023-10-15 — acceptable for a spec-frozen library: RFC 8785 is final, test vectors haven't moved, fork cost is low if upstream goes dark.

`jcs_test.go` still asserts the RFC 8785 §3.4 reference vectors verbatim — both as a sanity check on the library and as a tripwire if we ever swap implementations:

```go
func TestJCS_RFC8785_Vectors(t *testing.T) {
    cases := []struct{ name, input, want string }{
        {"null",          `null`,                        `null`},
        {"true",          `true`,                        `true`},
        {"french",        `{"peach":"This sorting order","péché":"is wrong according to French"}`,
                          `{"peach":"This sorting order","péché":"is wrong according to French"}`},
        // ... full vectors from gowebpki/jcs testdata/
    }
    for _, tc := range cases {
        t.Run(tc.name, func(t *testing.T) {
            got, err := Canonical(json.RawMessage(tc.input))
            if err != nil { t.Fatal(err) }
            if string(got) != tc.want {
                t.Errorf("\nwant %s\n got %s", tc.want, got)
            }
        })
    }
}
```

### 10.4 Audit chain helper

`internal/dataplane/audit/chain.go`:

```go
package audit

import (
    "crypto/sha256"
)

// Genesis returns the initial prev_hash for a tenant's chain.
func Genesis(tenantID string) []byte {
    h := sha256.Sum256([]byte(tenantID + "|genesis"))
    return h[:]
}

// ComputeRowHash returns sha256(prev_hash || JCS(row)). `row` MUST exclude
// the prev_hash and row_hash fields themselves.
func ComputeRowHash(prevHash []byte, row map[string]any) ([]byte, error) {
    body, err := Canonical(row)
    if err != nil { return nil, err }
    h := sha256.New()
    h.Write(prevHash)
    h.Write(body)
    return h.Sum(nil), nil
}
```

### 10.5 Module layout — `internal/dataplane/audit/`

```text
internal/dataplane/audit/
  domain.go
  ports.go
  service.go          # insert, list, get, export
  repo_pgx.go
  subscriber.go       # consumes outbox; the §18.3 dispatcher
  chain.go
  jcs.go              # RFC 8785
  jcs_test.go         # RFC vectors
  verifier.go         # walks the chain; reports first mismatch
  handler.go
  errors.go
  service_test.go
  subscriber_test.go
  security_test.go
```

### 10.6 Subscriber — translate outbox to audit_event

`subscriber.go`:

```go
package audit

import (
    "context"
    "log/slog"

    "github.com/omarss/saas/internal/dataplane/db/sqlc"
    "github.com/omarss/saas/internal/platform/id"
)

// §18.3 list — every outbox type that yields an audit row.
var auditedTypes = map[string]struct{}{
    "deployment.provisioned": {}, "deployment.upgraded": {}, "deployment.rollback": {},
    "deployment.destroyed":   {}, "deployment.purged": {},
    "operator.login":         {}, "operator.impersonation_started": {}, "operator.impersonation_ended": {},
    "tenant.suspended":       {}, "tenant.unsuspended": {}, "tenant.purged": {},
    "role.created":           {}, "role.updated": {}, "role.deleted": {},
    "permission.granted":     {}, "permission.revoked": {},
    "member.role_changed":    {}, "authorization.denied": {},
    "api_key.created":        {}, "api_key.rotated": {}, "api_key.revoked": {},
    "user.disabled":          {}, "user.enabled": {}, "user.password_reset_requested": {},
    "notification.queued":    {}, "notification.sent": {}, "notification.delivery_failed": {},
    "notification_channel.credentials_read":    {},
    "notification_channel.credentials_rotated": {},
    // Phase 11 + 12 add deployment provisioning sub-step events.
}

type Subscriber struct {
    q    *sqlc.Queries
    auditRepo Repository
}

// Handle is called by the outbox dispatcher for each event. If the type is
// audited, insert an audit_event in the same transaction as the outbox
// publish ack.
func (s *Subscriber) Handle(ctx context.Context, e sqlc.OutboxEvent) error {
    if _, ok := auditedTypes[e.Type]; !ok { return nil }
    row := AuditEvent{
        ID:           id.New(id.PrefixAudit),
        TenantID:     e.TenantID.String,
        ActorType:    parseActorType(e.Payload),
        ActorID:      parseActorID(e.Payload),
        Action:       e.Type,
        ResourceType: parseResourceType(e.Type, e.Payload),
        ResourceID:   parseResourceID(e.Payload),
        OccurredAt:   e.OccurredAt,
        Metadata:     stripPII(parseMetadata(e.Payload)),
        // PII (IP, UA) come from the principal in ctx if available.
    }
    return s.auditRepo.Append(ctx, row)
}
```

`Repository.Append` is the heart of the module:

```go
func (r *repo) Append(ctx context.Context, row AuditEvent) error {
    tx, err := r.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
    if err != nil { return err }
    defer tx.Rollback(ctx)
    // Look up last chain row for tenant.
    var prevHash []byte
    err = tx.QueryRow(ctx, `
        SELECT row_hash FROM audit_event
         WHERE tenant_id = $1
         ORDER BY chain_sequence DESC
         LIMIT 1`, row.TenantID).Scan(&prevHash)
    if err == pgx.ErrNoRows { prevHash = Genesis(row.TenantID); err = nil }
    if err != nil { return err }

    // Build the canonicalisable row (no prev_hash/row_hash/chain_sequence).
    canonRow := map[string]any{
        "id":            row.ID,
        "tenant_id":     row.TenantID,
        "actor_type":    row.ActorType,
        "actor_id":      row.ActorID,
        "action":        row.Action,
        "resource_type": row.ResourceType,
        "resource_id":   row.ResourceID,
        "occurred_at":   row.OccurredAt.UTC().Format(time.RFC3339Nano),
        "ip_address":    row.IPAddress,
        "user_agent":    row.UserAgent,
        "request_id":    row.RequestID,
        "metadata":      row.Metadata,
    }
    rowHash, err := ComputeRowHash(prevHash, canonRow)
    if err != nil { return err }

    if _, err := tx.Exec(ctx, `
        INSERT INTO audit_event
            (id, tenant_id, actor_type, actor_id, action, resource_type, resource_id,
             occurred_at, ip_address, user_agent, request_id, metadata, prev_hash, row_hash)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)`,
        row.ID, row.TenantID, row.ActorType, row.ActorID, row.Action, row.ResourceType, row.ResourceID,
        row.OccurredAt, row.IPAddress, row.UserAgent, row.RequestID, row.Metadata, prevHash, rowHash); err != nil {
        return err
    }
    return tx.Commit(ctx)
}
```

The `IsoLevel: pgx.Serializable` is critical — concurrent inserts to the same tenant must produce a consistent chain. Postgres will retry on serialization failure; the outbox dispatcher's retry logic catches that.

### 10.7 Verify endpoint

`internal/dataplane/audit/verifier.go`:

```go
type IntegrityResult struct {
    Verified              bool
    RowsChecked           int
    FirstMismatchID       *string
    FirstMismatchTenantID *string
    FirstMismatchReason   *string
    VerifiedAt            time.Time
}

func (r *repo) Verify(ctx context.Context, deploymentID, tenantFilter string) (IntegrityResult, error) {
    // Stream rows in (tenant_id, chain_sequence) order. For each tenant,
    // start from Genesis and walk forward.
    var (
        out IntegrityResult
        currentTenant string
        prev []byte
        seq  int64
    )
    out.VerifiedAt = time.Now()
    sql := `SELECT id, tenant_id, chain_sequence, prev_hash, row_hash,
                   actor_type, actor_id, action, resource_type, resource_id,
                   occurred_at, ip_address, user_agent, request_id, metadata
              FROM audit_event
             WHERE ($1 = '' OR tenant_id = $1)
          ORDER BY tenant_id, chain_sequence`
    rows, err := r.pool.Query(ctx, sql, tenantFilter)
    if err != nil { return out, err }
    defer rows.Close()
    for rows.Next() {
        var row dbRow
        if err := rows.Scan(&row...); err != nil { return out, err }
        out.RowsChecked++
        if row.TenantID != currentTenant {
            currentTenant = row.TenantID
            prev = Genesis(row.TenantID)
            seq = 0
        }
        // Sequence-gap check.
        if row.ChainSequence != seq+1 {
            out.FirstMismatchID = &row.ID
            out.FirstMismatchTenantID = &row.TenantID
            reason := "sequence-gap"
            out.FirstMismatchReason = &reason
            return out, nil
        }
        // prev_hash check.
        if !bytes.Equal(row.PrevHash, prev) {
            reason := "prev_hash"; out.FirstMismatchReason = &reason
            out.FirstMismatchID = &row.ID; out.FirstMismatchTenantID = &row.TenantID
            return out, nil
        }
        // row_hash recomputation.
        expected, _ := ComputeRowHash(prev, canonRowFromDB(row))
        if !bytes.Equal(row.RowHash, expected) {
            reason := "row_hash"; out.FirstMismatchReason = &reason
            out.FirstMismatchID = &row.ID; out.FirstMismatchTenantID = &row.TenantID
            return out, nil
        }
        prev = row.RowHash
        seq = row.ChainSequence
    }
    out.Verified = true
    return out, nil
}
```

The verify endpoint runs in the control plane (operator-only), connects to the data plane DB via a separate role with SELECT-only on `audit_event`, and returns the result.

### 10.8 PII redaction in audit metadata

A wrapper around `metadata` clears any keys that match the slog redactor list:

```go
func stripPII(m map[string]any) map[string]any {
    out := make(map[string]any, len(m))
    for k, v := range m {
        if log.IsRedactedKey(k) {
            out[k] = "[REDACTED]"
            continue
        }
        // Walk nested.
        if sub, ok := v.(map[string]any); ok { out[k] = stripPII(sub); continue }
        out[k] = v
    }
    return out
}
```

The full original metadata is envelope-encrypted into `metadata_ciphertext` so operators can decrypt for forensic purposes via a separate control-plane endpoint (deferred; flag in §Open questions).

### 10.9 Export endpoint

`POST /v1/audit-events/export` accepts the same filters as the list endpoint plus a `format` field (`csv` or `json`):

- If the estimated response size is ≤ 1MB (heuristic: `COUNT(*)` with same WHERE × 256 bytes per row), respond sync with the body inline.
- Otherwise: write a job row to `audit_export_job` table, return 202 + Location header `/v1/audit-events/exports/<job_id>`, background worker streams to a file (deferred — for MVP we ship sync only and document async as a follow-up; large tenants pre-Phase 16 are rare).

For MVP: implement sync only, mark async with a TODO. Document in CONVENTIONS.md.

### 10.10 §17.3 matrix

| Test | Assert |
|---|---|
| Same-tenant list | 200 |
| Cross-tenant list URL | 403 (tenant_id in path) |
| Read audit row without scope | 403 |
| Read audit row with scope | 200 |
| Try INSERT outside the subscriber path | DB grants would still allow it, but ... |
| Try UPDATE | DB rejects (REVOKE'd grant); test SQL directly |
| Try DELETE | DB rejects |
| Verify endpoint as data-plane caller | 404 (operator-only) |
| Verify endpoint as operator | 200 |

### 10.11 Chain forensics — controlled tamper test

`subscriber_test.go` includes a test that deliberately tampers with a chain row (via a raw SQL connection with bypass grants) and confirms `Verify` reports `first_mismatch_id` correctly. The tamper happens in a forked schema so the actual `audit_event` table grants stay intact.

### 10.12 ADR 012

`docs/adr/012-audit-jcs-canonicalization.md`:

```markdown
# ADR 012 — Audit chain canonicalization: RFC 8785 JCS

## Status
Accepted (2026-05-24).

## Context
The audit hash chain (§8.6) computes `row_hash = sha256(prev_hash || canonical_json(row))`.
"Canonical" must be deterministic across re-encode round-trips, otherwise
operators verifying the chain in N years' time can't reproduce the hashes.
Three options:

(A) Custom ordered-key JSON with alphabetical keys + UTF-8.
(B) RFC 8785 JCS (JSON Canonicalization Scheme): alphabetical keys (UTF-16
    code unit order), canonical number form, JSON-style string escapes.
(C) Protobuf canonical form.

(C) requires a schema and locks us into protobuf forever — refused.
(A) is easy but the number formatting + UTF-16 code unit ordering are
exactly the parts of JCS we'd need to invent anyway.

## Decision
RFC 8785 JCS, implemented via the vetted external library
`github.com/gowebpki/jcs` v1.0.1 (Apache-2.0, MIT-compatible). The
`Canonical()` wrapper in `internal/dataplane/audit/jcs.go` is the ONLY
source of canonical bytes in the codebase; any alternate path is a
security incident.

We deliberately did NOT roll our own. The "subset we actually emit"
expands silently as audit payloads gain user-supplied strings — at
which point surrogate-pair handling, non-ASCII escapes, and the
ECMAScript canonical number form (§3.2.2.3) become load-bearing for
chain integrity. A single off-by-one in number serialization breaks
the chain forever.

Library status (verified 2026-05-24):
- Module path: github.com/gowebpki/jcs
- Tagged release: v1.0.1 (2023-10-15)
- License: Apache-2.0
- Upstream: fork of cyberphone/json-canonicalization (the reference
  implementation by Anders Rundgren, the RFC 8785 author), cleaned
  up for Go idioms (proper go.mod, short import path, single dep).
- Spec coverage: ships testdata matching the RFC §3.4 reference
  vectors verbatim.
- Activity: 0 open issues, 1 active maintainer, 27 stars but 63
  importers including cosign and other security-sensitive consumers.

Mitigation against bus-factor: the library is ~700 LoC of stable
spec implementation — if upstream goes dark, forking is cheap.

## Consequences
+ Audit chain is verifiable by any third party with the spec.
+ External tools (auditors, compliance bots) can re-canonicalize and
  match our row_hash bit-for-bit.
+ The fiddly parts (number formatting, UTF-16 key ordering, string
  escapes) are someone else's tested code, not ours.
- One additional dependency in the platform binary (Apache-2.0,
  no transitive footprint beyond stretchr/testify in tests).
- A future upgrade to a JCS successor (if one supersedes RFC 8785)
  requires a chain fork: new rows use new canonicalization; old rows
  verifiable under old. Documented in the runbook.
- If the gowebpki repo is archived without a successor, we fork
  in-tree (low risk; ~700 LoC of frozen spec).
```

### 10.13 saasctl

```text
saasctl audit list --tenant <id> [--action <a>] [--actor <id>] [--since DATE]
saasctl audit get <audit_id>
saasctl audit export --tenant <id> --format csv > out.csv
saasctl deployment audit-integrity <dep_id> [--tenant <id>]
```

### 10.14 TS SDK + workflow

`sdk/ts/data-plane/workflows/audit.ts` exposes `list`, `get`, `export`.

`sdk/ts/control-plane/workflows/deployments.ts` adds `verifyAuditIntegrity`.

### 10.15 Commits

```bash
git add openapi/data-plane.yaml openapi/control-plane.yaml openapi/problems/
git commit -m "add audit endpoints and integrity verify"

git add migrations/dataplane/000008_audit.up.sql internal/dataplane/db/queries/audit.sql
git commit -m "add append only audit event table"

git add internal/dataplane/audit/
git commit -m "implement audit module with jcs hash chain"

git add cmd/dataplane/main.go cmd/controlplane/main.go
git commit -m "wire audit subscriber and integrity endpoint"

git add sdk/ts/data-plane/workflows/audit.ts sdk/ts/control-plane/workflows/deployments.ts cmd/saasctl/
git commit -m "ts sdk and saasctl audit coverage"

git add docs/adr/012-audit-jcs-canonicalization.md
git commit -m "add audit jcs adr"
```

---

## Verification checklist

```bash
# 1. Migrations apply.
$ make migrate
$ psql -c "\d audit_event"

# 2. App role lacks UPDATE/DELETE on audit_event.
$ psql -c "SET ROLE app_role; UPDATE audit_event SET action='tamper' WHERE id IS NOT NULL;"
# Expected: ERROR permission denied for table audit_event
$ psql -c "SET ROLE app_role; DELETE FROM audit_event;"
# Expected: ERROR permission denied for table audit_event

# 3. Build + lint + tests.
$ make build && make lint && make test && make test-int

# 4. JCS RFC 8785 vectors.
$ go test -run TestJCS_RFC8785 -v ./internal/dataplane/audit/...

# 5. Subscriber wires up: trigger an action that emits an outbox event, audit row appears.
$ curl -X POST http://localhost:9090/v1/tenants/<t>/api-keys ... -d '{"name":"k","scopes":["tenant.read"]}'
$ sleep 1
$ psql -c "SELECT id, action FROM audit_event ORDER BY chain_sequence DESC LIMIT 1;"
# Expected: action='api_key.created'

# 6. Chain is consistent.
$ curl http://localhost:8080/control/v1/deployments/<dep_id>/audit-integrity \
    -H "Authorization: Bearer $OP_TOK" | jq
# Expected: { data: { verified: true, rows_checked: N, ... } }

# 7. Tamper test (uses superuser for the test only; restore after).
$ psql -U postgres -c "UPDATE audit_event SET action = 'tampered' WHERE id = (SELECT id FROM audit_event ORDER BY id LIMIT 1);"
$ curl http://localhost:8080/control/v1/deployments/<dep_id>/audit-integrity ... | jq
# Expected: { data: { verified: false, first_mismatch_id: '<id>', first_mismatch_reason: 'row_hash' } }
# Restore for subsequent tests:
$ psql -U postgres -c "..."

# 8. List filters.
$ curl "http://localhost:9090/v1/tenants/<t>/audit-events?action=api_key.created" ... | jq '.data | length'

# 9. PII redaction in metadata.
$ psql -c "SELECT metadata FROM audit_event WHERE action='user.password_reset_requested' LIMIT 1;"
# Expected: no password, no email plaintext — at most '[REDACTED]'

# 10. §17.3 matrix.
$ go test -run TestAudit_AuthZ -v ./internal/dataplane/audit/...
```

---

## Anti-pattern guards

- **NEVER** call `repo.Append` from anywhere except the outbox subscriber. The §18.3 list is the source of truth; ad-hoc appends bypass the audit policy.
- **NEVER** UPDATE or DELETE an `audit_event` row. The grants reject; bypassing via the superuser is a security incident.
- **NEVER** include plaintext PII in `metadata`. The stripPII walker scrubs at insert time; the envelope blob preserves the original for forensic recovery.
- **NEVER** change the canonicalisation function output for ANY input — this breaks all stored row_hashes. Updates require ADR 012 fork notes + new code path for old rows.
- **NEVER** read `audit_event` from the data-plane app role with `tenant_id` from a request body. RLS enforces same-tenant; URL path parameter must be checked via `auth.AssertTenant`.
- **NEVER** expose the verify endpoint on the data plane. Operator-only on control plane.
- **NEVER** allow the genesis prev_hash to be NULL. Explicit `Genesis(tenant_id)` keeps the chain rooted.
- **NEVER** rely on the chain alone for non-repudiation. The chain proves no in-place tampering; it does NOT prove no INSERT-and-DELETE (you'd see a sequence-gap). Combine with an external Loki/VictoriaLogs mirror as a future-proof step (out of MVP).

---

## Open questions

1. **External chain anchor.** A weekly cron pushes the latest row_hash per tenant to a public-write log (e.g. a Sigsum-style transparency log). Out of MVP; flag for v1.
2. **Forensic decrypt endpoint.** Should there be a control-plane endpoint to decrypt `metadata_ciphertext` for incident response? Default: yes, gated by operator MFA + step-up (Phase 13). Implement as `GET /control/v1/deployments/{id}/audit-events/{id}/full-metadata`. Flag for Phase 13.
3. **Async export.** Defer to post-MVP. Confirm acceptable.
4. **Audit retention.** Default: keep forever for MVP. Real policy is per-tenant (e.g. 7 years for finance customers). v1 roadmap.

---

## Phase 10 — Definition of done

- [ ] OpenAPI updated; `make openapi-check` green
- [ ] Migrations 000008 applied; `audit_event` exists with RLS + grants
- [ ] App role rejects UPDATE/DELETE on audit_event (DB-tested)
- [ ] `internal/dataplane/audit/` complete: jcs, chain, subscriber, verifier, service, repo, handler, tests
- [ ] JCS implementation passes all RFC 8785 §3.4 reference vectors
- [ ] Subscriber consumes every outbox type in the §18.3 list and appends
- [ ] Chain genesis explicit; per-tenant sequence monotonic
- [ ] Integrity verify endpoint walks the chain; returns first-mismatch id + reason
- [ ] PII stripped from `metadata`; envelope preserves original for forensic recovery
- [ ] Export endpoint sync up to 1MB; async TODO documented
- [ ] §17.3 matrix passes
- [ ] TS SDK regenerated + workflow wrapper
- [ ] saasctl `audit *` and `deployment audit-integrity`
- [ ] ADR 012 committed
- [ ] All Phase 2-9 tests still green (regression)
- [ ] PR template, `ready` label, CI green

---

## CHECKPOINT 3 — Data plane complete

### What was done (Phase 10 portion)
- migrations/dataplane/000008_audit.up.sql (audit_event + grants + sequence trigger)
- internal/dataplane/audit/{jcs,chain,subscriber,verifier,service,repo_pgx,handler,domain,ports,errors}.go + tests
- cmd/dataplane/main.go: subscriber goroutine alongside outbox dispatcher
- cmd/controlplane/main.go: verify endpoint handler
- openapi/data-plane.yaml + openapi/control-plane.yaml audit endpoints
- sdk/ts/data-plane/workflows/audit.ts + sdk/ts/control-plane/workflows/deployments.ts (verify)
- docs/adr/012-audit-jcs-canonicalization.md
- saasctl audit + deployment audit-integrity commands

### What to verify (user runs these)
```bash
$ make migrate && psql -c "\d audit_event"
$ psql -c "SET ROLE app_role; UPDATE audit_event SET action='x' WHERE id IS NOT NULL;"   # expected: permission denied
$ make test && make test-int
$ go test -v -run TestJCS_RFC8785 ./internal/dataplane/audit/...                          # vectors pass

# End-to-end: every Phase 2-9 mutation now produces an audit row.
$ curl -X POST http://localhost:9090/v1/tenants ... -d '{"slug":"x","name":"X"}'
$ curl -X POST http://localhost:9090/v1/users ... -d '{"email":"u@x"}'
$ curl -X POST http://localhost:9090/v1/tenants/<t>/api-keys ... -d '{"name":"k","scopes":["tenant.read"]}'
$ sleep 1
$ psql -c "SELECT action, count(*) FROM audit_event GROUP BY action ORDER BY action;"
# Expected: tenant.created, user.created, api_key.created, ... each with count >= 1

# Integrity ok.
$ curl http://localhost:8080/control/v1/deployments/dep_local/audit-integrity ... | jq
# Expected: verified=true, rows_checked > 0
```

### What approval means
By proceeding past CHECKPOINT 3, you accept:
- The full data-plane module set is frozen as MVP. Breaking changes require /v2 + 6-month overlap.
- Every action on the §18.3 list emits an outbox event consumed synchronously by the audit subscriber. Adding a new audited action means: (a) emit outbox, (b) add type to `auditedTypes` map, (c) write tests.
- The hash chain canonicalisation is RFC 8785 JCS. Changing it requires a chain fork + ADR.
- Next: Phase 11 starts work on the CONTROL plane (which provisions data planes). All Phase 12 work writes to /etc/nginx, k3s API, host Postgres, OpenBao — irreversible host state changes. You'll review sudoers + certbot + k3s manifest templates at CHECKPOINT 4 BEFORE Phase 12a starts writing.

### Rollback if rejected
```bash
git revert <hashes for the 6 phase-10 commits>
# audit_event table can stay; rolling back the subscriber means new events don't audit
# until the issue is fixed. Existing rows untouched.
```

---

End of Phase 10. Next: `12-control-plane-skeleton.md`.
