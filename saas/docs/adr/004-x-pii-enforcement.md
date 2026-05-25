# ADR 004 — x-pii enforcement via x-oapi-codegen-extra-tags + reflection middleware

## Status

Accepted (2026-05-24, Phase 3).

## Context

AGENTS.md §18.5 mandates that PII fields are never logged in plaintext.
§18.7 mandates envelope encryption for fields declared `x-pii: true` at the
OpenAPI layer. The challenge: oapi-codegen v2.7 does not propagate arbitrary
`x-` extensions to generated struct tags (foundations §2, §3); a raw
`x-pii: true` marker on a schema disappears after codegen.

Two consumers need to act on PII flags:

1. The slog handler — to scrub field values in log records.
2. The persistence layer — to envelope-encrypt values before the row goes
   to disk, and verify `kid == deployment_id` on decrypt.

If we relied on per-call manual encryption, "I forgot to encrypt this
field" becomes a recurring incident. We need a mechanism that survives
codegen and applies uniformly.

## Decision

Author every PII / sensitive field with the `x-oapi-codegen-extra-tags`
extension oapi-codegen DOES forward:

```yaml
properties:
  email:
    type: string
    format: email
    x-oapi-codegen-extra-tags:
      pii: "true"
      sensitive: "true"
```

oapi-codegen emits the Go struct field as:

```go
Email string `json:"email" pii:"true" sensitive:"true"`
```

Two consumers read this tag pair via reflection:

1. **`internal/platform/log/scrub_struct.go`** — walks any struct passed to
   slog and substitutes `[REDACTED]` for tagged fields in the JSON output.
2. **`internal/platform/crypto/encrypt_persist.go`** — walks structs at
   the persistence boundary and calls `Encryptor.EncryptField` for each
   tagged field. The Encryptor interface is declared in Phase 3; the
   OpenBao-backed implementation lands in Phase 4
   (`internal/platform/crypto/envelope/`).

A static keyset (`internal/platform/log/redact.go`) supplements the tag
walker for HTTP-header-style keys (`authorization`, `cookie`, `vault_token`,
etc.) that never flow through a tagged struct.

## Consequences

- Single source of truth: PII annotations live in OpenAPI, not in Go
  source. Reviewers see the contract change in the spec diff.
- Forgotten-tag failure mode is silent at write time but caught at log
  time — the static keyset still scrubs obvious names (`email`,
  `password`, `phone` if added). Defense in depth: codegen template + lint
  + redactor + review.
- The reflection walker is hot-path code for any handler that logs a
  request body. We benchmark before the first release; the walker only
  descends into top-level struct fields (no recursive descent) to keep
  cost bounded.
- Adding a new PII field is a three-line OpenAPI change; no Go changes,
  no migration changes beyond the column itself.

## Alternatives considered

- **Manual encryption call at every write** — rejected. Too easy to
  forget on a hot deadline.
- **Build-time codegen of a `redactor` package per spec** — viable but
  doubles the codegen footprint. The reflection walker is ~50 LOC and
  covers both the log and persist paths.
- **gomarkdoc / docgen scrubbing** — addresses logs only, leaves the
  persist boundary unguarded.

## Revisit

When a new sensitive field type lands that doesn't fit the string-only
walker (binary blobs, deeply nested PII), extend the walker rather than
adding a parallel mechanism.

## Reference implementation

The persistence walker lives in
`internal/platform/crypto/encrypt_persist.go`. Two entry points:

- `EncryptPIIFields(ctx, enc, deploymentID, resourceType, resourceID, v)`
- `EncryptPIIFieldsStrict(ctx, enc, deploymentID, resourceType, resourceID, v)`

Both bind AAD to the quad
`deployment_id || "|" || resource_type || "|" || resource_id || "|" ||
field_name`. Read-path repositories MUST call `crypto.FieldAAD(...)` with
the SAME triple when invoking `Decryptor.DecryptField` — a mismatched AAD
fails the AEAD verify and the row fails closed. This is the regression
guard against cross-resource ciphertext swap inside a single deployment
(Phase 6 audit finding; test:
`TestEncryptPIIFieldsStrict_AADRejectsCrossResourceSwap`).
