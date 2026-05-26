# ADR 016 — Shared OpenBao audit device with per-policy tagging (not per-Deployment audit files)

## Status

Accepted (Phase 12d, 2026-05-26).

## Context

Per AGENTS.md §18.7, every OpenBao operation must be audited with the
caller identity, the path accessed, and the response code. The Phase 4
bootstrap (`deploy/openbao/config/openbao.hcl` + `make openbao-init`)
enables exactly one file-backed audit device that writes to
`/openbao/logs/audit.log` inside the OpenBao container.

Phase 12d's per-Deployment provisioner needs to decide whether to add
an additional, dedicated audit device per Deployment (one file per
Deployment, separate paths) or rely on the single shared file with
policy-name tagging.

Two approaches were on the table:

1. **Per-Deployment file audit device**: enable
   `audit/file-<dep_id>` writing to
   `/openbao/audit/<dep_id>.log` during Apply; disable on Remove.
2. **Shared audit device, policy-tagged routing**: keep the single
   `/openbao/logs/audit.log` (created at Phase 4 bootstrap); every
   line carries `auth.metadata` with the policy name (= `saas-<dep_id>`)
   and the role name (= `<dep_id>`), letting the Phase 10 audit
   subscriber demultiplex per-Deployment entries from one file.

## Decision

We adopt approach **2** (single shared file with policy-tagged
routing) for MVP. Rationale:

| Criterion | (1) Per-Deployment | (2) Shared |
|---|---|---|
| Scales to 100s of Deployments | NO — OpenBao has a fixed limit of audit devices (~10 in tested versions; documented limit not formally pinned in OpenBao docs but matches Vault's `maxLogicalAuditMounts`) | YES — one device regardless of Deployment count |
| Operationally simple | NO — destroy reconciler must remember to disable audit device when removing a Deployment, otherwise stale devices accumulate | YES — no per-Deployment audit lifecycle |
| File rotation | Independent per file, but more files to rotate | One file to rotate via logrotate / Loki tail / VictoriaLogs sink |
| Per-Deployment forensics | Direct: `tail /openbao/audit/<dep_id>.log` | Indirect: `jq '.auth.metadata.policies[]' <one file>` — but the Phase 10 audit subscriber already produces the per-Deployment `audit_event` table, so direct file inspection is rarely needed |
| Failure isolation | If `/openbao/audit/dep_X.log` fills the disk, only dep_X's audit halts (OpenBao blocks writes when ANY audit device fails — same outcome) | Same outcome — OpenBao blocks all writes when its only audit device fails |
| Production migration | Each per-Deployment file becomes its own Loki / VictoriaLogs stream | Single stream; filter by `auth.metadata.policies` field |

The "failure isolation" row is the most important one: OpenBao's
audit behaviour is to **block all writes** when ANY enabled audit
device cannot record an event. So per-Deployment devices do not
isolate failures — they multiply the failure surface (more files,
more chances for one of them to be full or unwriteable).

The Phase 10 audit subscriber consumes the platform outbox (not the
OpenBao audit file directly) and writes per-Deployment `audit_event`
rows. OpenBao's audit file is the secondary, defense-in-depth record
that lets operators reconstruct OpenBao-side activity independently
of the application-level audit chain. Either approach satisfies that
defense-in-depth requirement.

## Consequences

### Positive

- The Phase 12d provisioner is simpler — no audit device lifecycle to
  manage. The adapter's `Apply` and `Remove` skip the audit step
  entirely; `VerifyAccess` only confirms that at least one audit
  device is enabled.
- No risk of exhausting OpenBao's audit device limit at scale.
- One file rotation cron / one log sink configuration.
- The shared file's existing pre-Phase-12d wiring (from Phase 4
  bootstrap) does not need to change.

### Negative

- Per-Deployment forensics requires `jq`-style filtering on the
  shared file rather than a direct `tail`. Documented in the Phase 12d
  runbook section.
- A future opt-in for per-Deployment audit (e.g. a single
  compliance-sensitive Deployment that needs its own audit stream)
  must be re-introduced as a separate code path. The `audit.go`
  helpers in the adapter retain the `auditDevicePath(dep_id)` builder
  for this future path; `ErrAuditDeviceConflict` is kept as a sentinel.

### Out of scope

- Opt-in per-Deployment audit devices. Reserved for a future ADR if a
  customer requires it; the adapter's API surface is forward-compatible
  (`ApplyInput.AuditLogPath` is reserved for this case).
- Streaming OpenBao audit to Loki / VictoriaLogs. Phase 15 (observability)
  wires the sink; Phase 12d just confirms the file device is present.
- Tamper-evident audit storage (e.g. signed log lines). OpenBao's audit
  device hashes sensitive request/response fields; tamper-evidence
  requires an external log integrity layer that is out of MVP scope.

## Anti-patterns

- **Never** disable the shared audit device while any Deployment is
  active. OpenBao will refuse to write any new state — provisioning
  halts, transit operations halt. The `VerifyAccess` probe catches
  this and returns `ErrVerificationFailed` so a misconfigured cluster
  fails the CP-8 smoke before any per-Deployment state is created.
- **Never** add a per-Deployment audit device without disabling it on
  Remove. Stale audit devices accumulate and eventually hit OpenBao's
  cluster-wide limit.
- **Never** rely on the OpenBao audit file as the *primary* source of
  truth for application-level audit. The application emits outbox
  events to the audit subscriber (Phase 10); OpenBao's file is the
  defense-in-depth secondary record for crypto/KV operations only.
