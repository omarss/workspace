# ADR 018 — Host provisioner composition + destroy reconciler design

## Status

Accepted (2026-05-26, Phase 12e).

## Context

Phase 12a-d shipped four host-write adapters (nginx vhost + certbot,
k3s SSA, host Postgres CREATE DATABASE + role + grants, OpenBao
transit key + policy + k8s auth role + KV namespace) behind
`saasctl debug <adapter> apply|remove` helpers so CHECKPOINT 5/6/7/8
could verify each adapter's host writes one layer at a time.

Phase 12e composes the four into the AGENTS.md §6.2 13-step
provisioning sequence + adds the §6.3 upgrade / rollback, §6.6
restore, §18.6 purge, §18.7 freeze-keys flows + the destroy reconciler
that recovers from partial failures.

The questions this ADR records:

1. **One provisioner type, or two?** Phase 11 shipped
   `deployments.LocalProvisioner` (Postgres-only, the safe `make dev`
   default). Phase 12e adds the host-writing path. Do we replace
   LocalProvisioner or keep both?
2. **Where does the orchestrator live?** Inside the deployments
   package (tight coupling) or as a sibling package
   (`provision/sequence`)?
3. **How does the destroy reconciler discover partially-failed
   deployments?** Read directly from the deployments repository, or
   subscribe to events?
4. **How is the selection made at boot time?**

## Decision

### 1. Two provisioners, one interface, env-flag selection

Keep `LocalProvisioner` for tests and dev (no nginx / k3s / OpenBao
required to boot). Add `HostProvisioner` that delegates every method
to a `HostProvisionerSeq` shim around `sequence.Sequence`. Both
satisfy the existing `Provisioner` interface from Phase 11; no code
above the interface needs to know which one is wired.

`cmd/controlplane/main.go` selects via the `SAAS_HOST_PROVISIONER`
env flag:

```bash
SAAS_HOST_PROVISIONER=true   # composite path — needs nginx + k3s + OpenBao + Postgres
SAAS_HOST_PROVISIONER unset  # local-mode — Postgres-only
```

The flag defaults to off so the `make dev` flow keeps working
without spinning up nginx + k3s + OpenBao. Mirrors the
`SAAS_RBAC_ENFORCE_DESTRUCTIVE` pattern from Phase 8.

### 2. Orchestrator lives in `provision/sequence`

A standalone `internal/controlplane/provision/sequence/` package
owns:

- `Step` type with `Run` + `Rollback` callbacks
- `Sequence` orchestrator with per-step timeout + reverse-rollback
  on failure
- `Ledger` interface (in-memory impl shipped; pgx impl is a future
  hardening)
- `DestroyReconciler` goroutine that ticks every 30 s
- Lifecycle methods (`Upgrade`, `Rollback`, `Restart`, `Restore`,
  `Purge`, `FreezeKeys`)
- `HostShim` adapts `*Sequence` + `Adapters` to the
  `deployments.HostProvisionerSeq` interface

Rationale: the four adapters already live under `provision/<adapter>`.
A sibling `provision/sequence` package keeps them all under one
hexagon's outermost ring; `deployments` retains the resource model +
the Phase 11 `Provisioner` interface; the orchestrator is the
composition root, not a deployments-internal detail.

### 3. Destroy reconciler reads from the repository

The reconciler scans for deployments with `status IN ('failed',
'destroying', 'purging')` every 30 s and also for retention-expired
soft-deletes (`status='destroyed' AND retain_until < now()`). It does
NOT subscribe to events because:

- The event publisher (outbox) is at-least-once; the reconciler must
  be idempotent anyway. Reading the source-of-truth row directly is
  simpler than de-duping a stream.
- A control-plane crash + restart should not lose any pending
  cleanup. The repo always reflects the truth; an event channel does
  not.

The reconciler's behaviour matrix:

| Source status | Action                          | Target status |
|---------------|----------------------------------|---------------|
| `failed`      | walk ledger reverse + rollback   | `destroyed`   |
| `destroying`  | full teardown (all 4 adapters)   | `destroyed`   |
| `purging`     | full teardown (bypass retention) | `purged`      |
| `destroyed` AND `retain_until < now()` | full teardown | `purged` |

Rollback failure leaves the row in its source status so the next tick
retries on a longer back-off (controlled by the natural 30 s ticker).
Continuous failure is the operator's signal to investigate.

### 4. The §6.2 step ordering refinement

AGENTS.md §6.2 lists 13 steps but doesn't explicitly include the
OpenBao step. The refined order respects all phase dependencies:

```
1.  validate            (slug + DNS-safe)
2.  allocate_id         (dep_<ulid>)
3.  record_desired_state (INSERT + provision_step rows)
4.  openbao             (transit key + policy + k8s role + KV path)
5.  postgres            (CREATE DB + role + grants + migrations + RLS)
6.  seed                (bootstrap tenant + admin + API key)
7.  render_k3s          (kustomize render)
8.  k3s_apply           (SSA + WaitReady)
9.  render_nginx        (template render)
10. nginx_apply         (install + reload + certbot)
11. healthz             (poll public /healthz until 200)
12. flip_active         (status='active' + deployment.provisioned)
13. return_bootstrap    (handler reads from BootstrapStore)
```

OpenBao must precede Postgres so the generated app password has a KV
path to land in. k3s must precede nginx because the NodePort the
vhost targets is the k3s Service; the cert can't issue without a
reachable upstream. healthz is end-to-end: success confirms nginx +
cert + k3s + Postgres + OpenBao all wire up correctly.

## Consequences

### Positive

- LocalProvisioner stays as the easy boot path for `make dev` and
  unit tests; HostProvisioner is opt-in and fail-fast on
  misconfiguration.
- The four adapters remain independently testable; the orchestrator
  only ever calls their `Apply` / `Remove` surface.
- Partial-failure recovery is observable (the ledger) and automated
  (the reconciler) — no operator runbook required for the common
  cases.
- The §6.2 spec is encoded as a slice of `Step` values, so additions
  / re-orderings are a one-line PR rather than a 13-method
  refactor.

### Negative

- Two provisioners means two paths to maintain. Mitigated by the
  common `Provisioner` interface — anything new added to one MUST be
  added to the other (the compile-time interface assertion catches).
- The destroy reconciler is a goroutine; a crash takes 30 s + on
  the next process start to resume cleanup. Acceptable for the
  control-plane's single-replica MVP; future scale-out needs
  leader-elected reconciliation (out of MVP per
  `docs/plans/mvp/13e-provisioning-sequence.md` §"Open questions").
- The Ledger has an in-memory impl shipped; a process restart loses
  in-flight step state. The deployment row's `status` still drives
  the reconciler, so recovery works at the deployment level but not
  the per-step level. The pgx-backed Ledger (writing to the
  `deployment_provision_step` table created in migration 000002) is
  the documented next hardening step.

### Saasctl debug subtree removal

Phase 12a-d shipped `saasctl debug {nginx,k3s,postgres,bao}
apply|remove` for the CHECKPOINT 5/6/7/8 verification. Phase 12e's
composition removes those subcommands — the production
`saasctl deployment create / upgrade / rollback / restart / restore /
purge / freeze-keys / ledger` flow exercises the same adapters
through HostProvisioner. The debug helpers were a Phase-12 scaffold;
their job is done.

## Alternatives considered

- **Single provisioner, runtime-switched per method.** Rejected:
  every method on the interface would gain a "host or local?" branch.
  The interface seam is a cleaner boundary.
- **Reconciler as a separate process.** Rejected for MVP: more
  infrastructure to deploy + monitor; the same crash-recovery problem
  applies. v1 may revisit when fleet upgrades land.
- **Sync rollback in the orchestrator (no reconciler).** Rejected
  because a crash mid-rollback would leave the deployment in a
  corrupted state with no automated recovery. The reconciler is the
  liveness mechanism.
- **Per-Deployment audit device in OpenBao.** Rejected per ADR 016
  — OpenBao has a hard limit on enabled audit devices at the platform
  scale we target.

## References

- AGENTS.md §6.2 (the 13-step sequence), §6.3 (upgrade + rollback),
  §6.4 (destroy), §6.6 (restore), §18.6 (purge), §18.7 (freeze keys)
- `docs/plans/mvp/13e-provisioning-sequence.md` (the implementation
  plan this ADR backs)
- Phase 11 — `internal/controlplane/deployments/provisioner_local.go`
- Phase 12a — ADR 015 BYOD verification (no new ADR; the vhost step
  in §6.2 references this)
- Phase 12d — ADR 016 OpenBao shared audit device
