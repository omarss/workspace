# ADR 012 — Audit chain canonicalization: RFC 8785 JCS via gowebpki/jcs

## Status

Accepted (Phase 10, 2026-05-25).

## Context

The audit hash chain (AGENTS.md §8.6) computes

```text
row_hash = sha256(prev_hash || canonical_json(row))
```

per row, where `prev_hash` is the previous row's `row_hash` (or
`Genesis(tenant_id)` for the first row in a tenant's chain). "Canonical"
must be byte-identical across any re-encode round-trip — without that
property, an external auditor verifying the chain in N years cannot
reproduce our hashes, and the entire integrity guarantee evaporates.

Three options were considered:

(A) **Custom ordered-key JSON** — alphabetical keys + UTF-8.
(B) **RFC 8785 JCS** (JSON Canonicalization Scheme): alphabetical keys
    in UTF-16 code-unit order, ECMAScript-canonical number form,
    JSON-style string escapes.
(C) **Protobuf canonical form** — requires a schema, locks us into
    protobuf forever.

(C) is rejected: an immutable audit format that requires schemas is the
opposite of what an "auditor verifies in N years" use case wants — we
should be able to hand someone the row + the spec and have them recompute
the hash.

(A) is superficially simpler but the parts of JCS that we'd need to
invent — UTF-16 key ordering when keys differ only by surrogate pairs,
ECMAScript canonical number form for floats, and the JSON string-escape
rules — are exactly the parts that would break the chain silently when
audit payloads gain new field shapes (e.g. user-supplied strings via a
notification.delivery_failed metadata blob).

## Decision

**RFC 8785 JCS**, implemented via the vetted external library
`github.com/gowebpki/jcs` v1.0.1 (Apache-2.0). The wrapper at
`internal/dataplane/audit/jcs.go` (`audit.Canonical` /
`audit.CanonicalBytes`) is the **only** source of canonical bytes in the
codebase; any alternate path is a security incident.

We deliberately did NOT roll our own. The "subset we actually emit"
expands silently as audit payloads gain user-supplied strings — at which
point surrogate-pair handling, non-ASCII escapes, and the ECMAScript
canonical number form become load-bearing for chain integrity. A single
off-by-one in number serialisation breaks the chain **forever** because
every subsequent row's `prev_hash` references the previous row's
`row_hash`.

Library status (verified 2026-05-25):

| Property | Value |
|---|---|
| Module path | `github.com/gowebpki/jcs` |
| Tagged release | v1.0.1 (2023-10-15) |
| License | Apache-2.0 (satisfies AGENTS.md §3.5 OSI-approved) |
| Upstream | fork of `cyberphone/json-canonicalization` — Anders Rundgren's reference implementation (RFC 8785 author) |
| Spec coverage | ships testdata matching RFC 8785 §3.4 reference vectors verbatim |
| Activity | 0 open issues; 1 active maintainer; 27 stars, 63 importers (including cosign and other security-sensitive consumers) |
| Footprint | single dep, no transitive footprint beyond stretchr/testify (test-only) |

Bus-factor mitigation: the library is ~700 LoC of stable spec
implementation. RFC 8785 is final; the spec doesn't move. If upstream
archives, forking in-tree is cheap and the tests pin behaviour via
`internal/dataplane/audit/jcs_test.go` (the RFC §3.4 reference vectors
serve as a tripwire if we ever swap implementations).

### Genesis hash

Every tenant's chain starts at an explicit synthetic prev_hash:

```text
Genesis(tenant_id) = sha256(tenant_id || "|audit-chain-genesis|v1")
```

We rejected `prev_hash = NULL`: an INSERT of a single row with NULL
predecessor is indistinguishable from the legitimate first row. Genesis
roots the chain to the tenant_id explicitly, and the version suffix
leaves a migration path if we ever need a v2 genesis derivation.

### Canonical body shape

The hashed body is the resource fields plus `metadata` — but NOT
`prev_hash`, `row_hash`, or `chain_sequence`. Including the hash columns
would make the hash self-referential. The `CanonicalBody()` method on
`audit.Event` is the authoritative shape; any field reordering is
inherently safe because JCS sorts keys alphabetically.

### Authorization on audit reads

For MVP, audit read endpoints (`GET /v1/tenants/{id}/audit-events`,
`GET /v1/audit-events/{id}`, `POST /v1/audit-events/export`) are gated
by `auth.AssertTenant` only. The `audit.read` permission exists in the
catalogue (migration 000008) and is reserved for the v1 RBAC hardening
pass. This mirrors the CONVENTIONS.md §2 retrofit pattern: full RBAC
gating on read endpoints lands when the self-service "join your tenant"
flow ships and the user→member resolution is no longer the placeholder
ActorID identity.

### Control-plane integrity verify endpoint

The chain-walking logic (`audit.VerifyChain`) ships in Phase 10. The
control-plane HTTP wiring (`GET /control/v1/deployments/{id}/audit-integrity`)
lands in Phase 11 when the control-plane main.go is wired. The function
signature is stable so the Phase 11 handler is a thin pass-through.

## Consequences

**Positive**

- Audit chain is verifiable by any third party with the RFC 8785 spec.
- External tools (auditors, compliance bots) can re-canonicalise and
  match our `row_hash` bit-for-bit.
- The fiddly parts (number formatting, UTF-16 key ordering, string
  escapes) are someone else's tested code, not ours.
- The RFC 8785 §3.4 reference vectors double as a regression tripwire.

**Negative**

- One additional dependency in the platform binary (Apache-2.0, no
  transitive footprint beyond stretchr/testify in tests).
- A future upgrade to a JCS successor (if one supersedes RFC 8785)
  requires a chain fork: new rows use new canonicalisation; old rows
  remain verifiable under old. Documented for the runbook.
- If the gowebpki repo is archived without a successor, we fork in-tree
  (low risk; ~700 LoC of frozen spec).

**Out of scope for Phase 10**

- External chain anchor (e.g. weekly push of `row_hash` to a Sigsum
  transparency log). Flagged for v1.
- Forensic decrypt endpoint for envelope-encrypted metadata. The
  Phase 10 audit table stores metadata in plaintext (PII stripped via
  the redactor list); the envelope-encrypted variant lands in Phase 13
  with operator MFA + step-up.
- Async export to a file. Sync-only for MVP; 1 MiB inline budget; the
  413 / async hand-off is wired in v1 alongside the Files module.

## References

- AGENTS.md §8.6 (Audit endpoints), §18.3 (audited events list).
- CONVENTIONS.md §11 (Audit invariants — added in this PR).
- Phase 10 plan: `docs/plans/mvp/11-audit-logs.md`.
- RFC 8785: https://datatracker.ietf.org/doc/html/rfc8785
- Library: https://github.com/gowebpki/jcs
