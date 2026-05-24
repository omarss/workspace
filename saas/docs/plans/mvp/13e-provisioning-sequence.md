# Phase 12e — Provisioning Sequence (§6.2 13 Steps) + Destroy Reconciler + Upgrade/Rollback/Restore/Purge

> **Goal**: Wire the four adapters (OpenBao Phase 12d, Postgres Phase 12c, k3s Phase 12b, nginx Phase 12a) into the formal §6.2 13-step Provision sequence. Each step is idempotent and records its completion in a per-Deployment `provision_step` ledger so a failure mid-sequence can be rolled back step-by-step in reverse. Land the destroy reconciler — a goroutine that picks up `status='failed'` and `status='destroying'` rows and runs the inverse of each completed step. Implement Upgrade (§6.3 — image flip + migration application), Rollback (§6.3 — image flip only, DB untouched), Restore (§6.6 — PITR into a NEW deployment_id), Purge (§18.6 — physical drop, NOT soft), and FreezeKeys (§18.7 — incident response). CHECKPOINT 9 ends in a first end-to-end real Deployment, with the user inspecting every artifact.
>
> **Why now**: Phase 12a-d each delivered one adapter. Phase 12e is the conductor: it composes them into the §6.2 sequence with proper rollback, runs the upgrade/rollback/restore/purge flows, and adds the destroy reconciler. Without it, partial-failure recovery is manual. Without the upgrade flow, the §17.4 provisioning tests can't be completed. This is the largest, most dangerous phase; it ends the data-plane + control-plane MVP cycle.
>
> **What this phase does NOT do**: No multi-host k3s (single-host MVP). No cross-region replication (out of MVP). No automated key rotation (operational). No fleet upgrade orchestration (Phase 15 DX adds `saasctl deployment upgrade --all` later as a v1 feature).
>
> **Maps to AGENTS.md**: §6.2 (the 13-step sequence verbatim), §6.3 (upgrade/rollback), §6.4 (destroy), §6.6 (backups + restore), §18.6 (purge), §18.7 (freeze keys), §17.4 (provisioning tests: happy + partial failure + upgrade + rollback + restore + purge). `01-foundations.md` §4 (golang-migrate behaviour), §9 (k3s rollout wait).
>
> **Estimated subagent sessions**: 3-4 (one for sequence + ledger; one for destroy reconciler + upgrade/rollback; one for restore + purge + freeze + tests; CHECKPOINT 9 demo session).

---

## Pre-flight

1. AGENTS.md §6.2, §6.3, §6.4, §6.5, §6.6, §17.4, §18.6, §18.7.
2. `01-foundations.md` §4, §9.
3. CHECKPOINT 8 approved (all four adapters individually verified).
4. Confirm host has WAL archiving configured on its Postgres cluster (one-time host setup; documented in `docs/runbooks/host-setup.md`).
5. Confirm host has enough free disk for backup snapshots (≥ 50 GB free; one `bao operator raft snapshot save` is ~100 MB per Deployment).

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Sequence step ledger | `provision_step` table in control-plane DB; one row per step per Deployment, tracking completion + timestamp + last error | Synthetic from outbox events (refused — replay-unsafe) |
| Idempotency at step level | Every step checks its own preconditions and is a no-op if already done | Track-and-skip via ledger only (refused — ledger drift) |
| Rollback strategy on failure | Run inverse of each completed step IN REVERSE ORDER; failure during rollback marks deployment `corrupted` for operator review | Best-effort cleanup (refused — leaves zombies) |
| Destroy reconciler | A goroutine in cmd/controlplane that polls every 30s for `status IN ('failed','destroying')` rows older than `retention_grace_seconds` | External worker (refused — adds infra) |
| Upgrade migration policy | Run ALL pending migrations during upgrade; refuse upgrade if the new image version is older than the current | Manual migration trigger (refused — ops burden) |
| Rollback DB policy | DO NOT touch the DB on rollback. Migrations are backward-compatible with the previous image for ONE release (§27 enforced by per-PR review) | DB snapshot+restore (refused — overcomplicates) |
| Restore implementation | `pg_restore` from per-Deployment logical dump + walk forward via WAL archive to the requested PITR timestamp; provisions a NEW deployment with a NEW dep_id | In-place (refused — destroys current state) |
| Purge atomicity | Drop in order: k3s, nginx, certbot, Postgres, OpenBao, control-plane row. Each step idempotent. Audit row emitted BEFORE rows disappear so the chain remains verifiable. | Single transaction (refused — cross-system) |
| FreezeKeys behaviour | Disables transit + revokes the k8s auth role token + sets deployment status='frozen' (new enum value). Reverses are admin-only. | Hard-delete (refused — recoverability) |

If user disagrees, stop. The sequence ordering in particular is hard to change later because each step depends on prior artifacts.

---

## Tasks

### 12e.1 Provision step ledger

`migrations/controlplane/000003_provision_step.up.sql`:

```sql
CREATE TABLE provision_step (
    id              bigserial PRIMARY KEY,
    deployment_id   text NOT NULL REFERENCES deployment (id),
    step_name       text NOT NULL,             -- "openbao", "postgres", "k3s", "nginx", "certbot", "healthz", "seed"
    step_index      integer NOT NULL,          -- order within the sequence
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','done','failed','rolled_back')),
    started_at      timestamptz,
    completed_at    timestamptz,
    last_error      text,
    rolled_back_at  timestamptz,
    UNIQUE (deployment_id, step_name)
);
CREATE INDEX provision_step_dep_idx ON provision_step (deployment_id, step_index);

-- Add status values to deployment.
ALTER TABLE deployment DROP CONSTRAINT deployment_status_check;
ALTER TABLE deployment ADD CONSTRAINT deployment_status_check
    CHECK (status IN ('provisioning','active','upgrading','failed','destroyed','restoring','purged','frozen','corrupted'));
```

### 12e.2 Sequence orchestrator — `internal/controlplane/provision/sequence/`

```text
internal/controlplane/provision/sequence/
  orchestrator.go    # Sequence type; Run + Rollback
  steps.go           # Step type; default 13-step ordering
  ledger.go          # provision_step CRUD
  destroy.go         # destroy reconciler goroutine
  upgrade.go
  rollback.go
  restore.go
  purge.go
  freeze.go
  orchestrator_test.go
  destroy_test.go
```

`orchestrator.go`:

```go
package sequence

import (
    "context"
    "errors"
    "fmt"
    "time"
)

type Step struct {
    Name    string
    Run     func(ctx context.Context, dep *Deployment) error
    Rollback func(ctx context.Context, dep *Deployment) error
}

type Sequence struct {
    Steps  []Step
    Ledger *Ledger
    Events EventPublisher
}

// Run executes every step in order, recording each in the ledger. On failure,
// it rolls back the completed steps in reverse order. Returns either the
// BootstrapResult (from the seed step) or the failure reason.
func (s *Sequence) Run(ctx context.Context, dep *Deployment) (BootstrapResult, error) {
    var boot BootstrapResult
    completed := []int{}
    for i, step := range s.Steps {
        if err := s.Ledger.Start(ctx, dep.ID, step.Name, i); err != nil { return boot, err }
        runCtx, cancel := context.WithTimeout(ctx, stepTimeout(step.Name))
        err := step.Run(runCtx, dep)
        cancel()
        if err != nil {
            _ = s.Ledger.Fail(ctx, dep.ID, step.Name, err)
            // Roll back completed steps in reverse.
            s.rollbackRange(ctx, dep, completed)
            return boot, fmt.Errorf("step %s: %w", step.Name, err)
        }
        if step.Name == "seed" {
            // The seed step writes the bootstrap result; pull from ledger metadata.
            if b, _ := s.Ledger.GetBootstrap(ctx, dep.ID); b != nil { boot = *b }
        }
        _ = s.Ledger.Done(ctx, dep.ID, step.Name)
        completed = append(completed, i)
    }
    return boot, nil
}

// rollbackRange runs Rollback() on each step in reverse. Failures during
// rollback escalate the deployment to status='corrupted' for operator review.
func (s *Sequence) rollbackRange(ctx context.Context, dep *Deployment, indices []int) {
    for i := len(indices) - 1; i >= 0; i-- {
        step := s.Steps[indices[i]]
        if step.Rollback == nil { continue }
        rbCtx, cancel := context.WithTimeout(ctx, stepTimeout(step.Name))
        if err := step.Rollback(rbCtx, dep); err != nil {
            _ = s.Ledger.RollbackFailed(ctx, dep.ID, step.Name, err)
            // Mark deployment corrupted; the destroy reconciler retries with longer back-off.
            _ = s.Events.Publish(ctx, "deployment.rollback_failed", "", map[string]any{
                "deployment_id": dep.ID, "step": step.Name, "error": err.Error(),
            })
        } else {
            _ = s.Ledger.RolledBack(ctx, dep.ID, step.Name)
        }
        cancel()
    }
}
```

### 12e.3 Default 13-step sequence — `steps.go`

```go
func DefaultSteps(openbao *openbao.Adapter, pg *postgres.Adapter, k3s *k3s.Adapter, ng *nginx.Adapter) []Step {
    return []Step{
        {   // step 1: validate slugs (handled at handler; no-op here but logged for audit)
            Name: "validate",
            Run:  noop,
        },
        {   // step 2: allocate deployment_id (set by handler; ledger marks done)
            Name: "allocate_id",
            Run:  noop,
        },
        {   // step 3: record desired state row (handler already did this)
            Name: "record_desired_state",
            Run:  noop,
        },
        {   // step 4: OpenBao transit key + policy + auth role + KV namespace + HMAC keys
            Name: "openbao",
            Run:  openbao.Provision,
            Rollback: openbao.Purge,
        },
        {   // step 5: Postgres DB + role + grants + migrations + KV password
            Name: "postgres",
            Run:  pg.Provision,
            Rollback: pg.Purge,
        },
        {   // step 6: seed bootstrap tenant + admin + role + API key
            Name: "seed",
            Run:  func(ctx context.Context, d *Deployment) error {
                b, err := pg.Seed(ctx, d)
                if err != nil { return err }
                return ledger.StoreBootstrap(ctx, d.ID, b)
            },
            Rollback: noop, // covered by postgres.Purge
        },
        {   // step 7: render k3s manifests (filesystem only; no API call yet)
            Name: "render_k3s",
            Run:  k3s.RenderOverlay,
            Rollback: k3s.RemoveOverlay,
        },
        {   // step 8: k3s apply (ns + sa + deployment + service + 3 NPs)
            Name: "k3s_apply",
            Run:  k3s.Provision,
            Rollback: k3s.Destroy,
        },
        {   // step 9: render nginx vhost
            Name: "render_nginx",
            Run:  ng.RenderTemplate,    // writes to deploy/nginx/vhosts/<dep_id>.conf staging
            Rollback: noop,
        },
        {   // step 10: install + reload nginx + certbot
            Name: "nginx_apply",
            Run:  func(ctx context.Context, d *Deployment) error {
                if err := ng.ApplyVhost(ctx, vhostInput(d)); err != nil { return err }
                return ng.IssueCertificate(ctx, d.ID, d.PrimaryVhost, d.CustomDomains)
            },
            Rollback: func(ctx context.Context, d *Deployment) error {
                _ = ng.DeleteCertificate(ctx, d.ID)
                return ng.RemoveVhost(ctx, d.ID)
            },
        },
        {   // step 11: wait for /healthz via public URL
            Name: "healthz",
            Run:  waitForPublicHealth,
            Rollback: noop,
        },
        {   // step 12: flip status active + emit event
            Name: "flip_active",
            Run:  func(ctx context.Context, d *Deployment) error {
                if err := depRepo.UpdateStatus(ctx, d.ID, "active"); err != nil { return err }
                return events.Publish(ctx, "deployment.provisioned", "", map[string]any{"deployment_id": d.ID})
            },
            Rollback: noop,
        },
        {   // step 13: return bootstrap key (handler reads ledger.GetBootstrap)
            Name: "return_bootstrap",
            Run:  noop,
        },
    }
}
```

Step timeouts: `openbao=30s`, `postgres=2min`, `seed=30s`, `k3s_apply=5min` (matches Phase 12b's rollout wait), `nginx_apply=2min` (certbot can take a moment), `healthz=2min`. Per-step timeout prevents the orchestrator from hanging forever.

### 12e.4 Destroy reconciler

`destroy.go`:

```go
package sequence

import (
    "context"
    "log/slog"
    "time"
)

type DestroyReconciler struct {
    Repo   DeploymentRepo
    Seq    *Sequence
    Period time.Duration       // default 30s
}

func (r *DestroyReconciler) Run(ctx context.Context) error {
    t := time.NewTicker(r.Period)
    defer t.Stop()
    for {
        select {
        case <-ctx.Done(): return ctx.Err()
        case <-t.C: r.tick(ctx)
        }
    }
}

func (r *DestroyReconciler) tick(ctx context.Context) {
    // Status='failed' → run rollback of any completed steps.
    failed, _ := r.Repo.ListByStatus(ctx, "failed", 10)
    for _, d := range failed {
        slog.Info("reconciler: handling failed deployment", "deployment_id", d.ID)
        // Look up completed steps from ledger; reverse them.
        if err := r.Seq.RollbackCompleted(ctx, d); err != nil {
            slog.Error("reconciler: rollback failed", "deployment_id", d.ID, "err", err)
            _ = r.Repo.UpdateStatus(ctx, d.ID, "corrupted")
            continue
        }
        _ = r.Repo.UpdateStatus(ctx, d.ID, "destroyed")
        _ = r.events.Publish(ctx, "deployment.destroyed", "", map[string]any{"deployment_id": d.ID})
    }

    // Status='destroyed' AND retain_until < now() → purge.
    expired, _ := r.Repo.ListExpiredSoftDeletes(ctx, time.Now(), 10)
    for _, d := range expired {
        slog.Info("reconciler: purging expired soft-delete", "deployment_id", d.ID)
        if err := r.Seq.Purge(ctx, &d); err != nil {
            slog.Error("reconciler: purge failed", "deployment_id", d.ID, "err", err)
            continue
        }
        _ = r.Repo.UpdateStatus(ctx, d.ID, "purged")
        _ = r.events.Publish(ctx, "deployment.purged", "", map[string]any{"deployment_id": d.ID})
    }
}
```

The reconciler is the central liveness mechanism: any partial state eventually resolves (active OR destroyed). The 30s tick is configurable.

### 12e.5 Upgrade

`upgrade.go`:

```go
func (s *Sequence) Upgrade(ctx context.Context, dep *Deployment, newImage string, runMigrations bool) error {
    // Refuse if new image version is older. SemVer compare; reject downgrades.
    if cmp := semver.Compare(newImage, dep.ImageVersion); cmp <= 0 {
        return ErrCannotDowngrade
    }
    _ = s.repo.UpdateStatus(ctx, dep.ID, "upgrading")

    // 1. Apply pending data-plane migrations (forward-only).
    if runMigrations {
        if err := s.pg.ApplyMigrationsOnly(ctx, dep); err != nil {
            _ = s.repo.UpdateStatus(ctx, dep.ID, "failed")
            return fmt.Errorf("upgrade: migrate: %w", err)
        }
    }
    // 2. k3s image patch via typed apply.
    if err := s.k3s.PatchImage(ctx, dep, newImage); err != nil {
        _ = s.repo.UpdateStatus(ctx, dep.ID, "failed")
        return fmt.Errorf("upgrade: k3s: %w", err)
    }
    // 3. Wait for rollout.
    if err := s.k3s.WaitForRollout(ctx, dep.Namespace, "data-plane"); err != nil {
        _ = s.repo.UpdateStatus(ctx, dep.ID, "failed")
        return fmt.Errorf("upgrade: rollout: %w", err)
    }
    // 4. Wait for public /healthz.
    if err := waitForPublicHealth(ctx, dep); err != nil {
        _ = s.repo.UpdateStatus(ctx, dep.ID, "failed")
        return err
    }
    // 5. Record revision.
    _ = s.revRepo.Append(ctx, dep.ID, newImage)
    _ = s.repo.UpdateImageVersion(ctx, dep.ID, newImage)
    _ = s.repo.UpdateStatus(ctx, dep.ID, "active")
    _ = s.events.Publish(ctx, "deployment.upgraded", "", map[string]any{
        "deployment_id": dep.ID, "image_version": newImage,
    })
    return nil
}
```

### 12e.6 Rollback

`rollback.go`:

```go
func (s *Sequence) Rollback(ctx context.Context, dep *Deployment) error {
    prev, err := s.revRepo.Previous(ctx, dep.ID, dep.ImageVersion)
    if err != nil { return err }
    // §6.3 + §27: do NOT roll back DB. Migrations are forward-compatible.
    if err := s.k3s.PatchImage(ctx, dep, prev.ImageVersion); err != nil { return err }
    if err := s.k3s.WaitForRollout(ctx, dep.Namespace, "data-plane"); err != nil { return err }
    if err := waitForPublicHealth(ctx, dep); err != nil { return err }
    _ = s.revRepo.MarkRolledBack(ctx, dep.ID, dep.ImageVersion)
    _ = s.repo.UpdateImageVersion(ctx, dep.ID, prev.ImageVersion)
    _ = s.events.Publish(ctx, "deployment.rollback", "", map[string]any{
        "deployment_id": dep.ID, "image_version": prev.ImageVersion,
    })
    return nil
}
```

### 12e.7 Restore (PITR into a NEW deployment_id)

`restore.go`:

```go
func (s *Sequence) Restore(ctx context.Context, source *Deployment, toTimestamp time.Time) (*Deployment, error) {
    // Validate WAL availability.
    if !s.backupAdapter.WALCoversTimestamp(ctx, source.DBName, toTimestamp) {
        return nil, ErrPITROutOfRange
    }
    // Provision a new deployment with a derived name (suffix).
    newDep := *source
    newDep.ID = id.New(id.PrefixDeployment)
    newDep.ProjectSlug = source.ProjectSlug + "-restored"
    newDep.DBName = fmt.Sprintf("saas_%s_%s_restored_%s", source.ProjectSlug, source.EnvironmentSlug, time.Now().Format("20060102t150405"))
    newDep.Namespace = fmt.Sprintf("saas-%s-%s-restored", source.ProjectSlug, source.EnvironmentSlug)
    newDep.PrimaryVhost = fmt.Sprintf("%s-restored.%s.saas.omarss.net", source.EnvironmentSlug, source.ProjectSlug)
    newDep.Status = "restoring"

    if err := s.repo.Create(ctx, newDep); err != nil { return nil, err }

    // 1. OpenBao + k3s + nginx as normal.
    // 2. Postgres: pg_basebackup or restore from snapshot + replay WAL to toTimestamp.
    if err := s.backupAdapter.RestoreToNewDB(ctx, source.DBName, newDep.DBName, toTimestamp); err != nil {
        _ = s.repo.UpdateStatus(ctx, newDep.ID, "failed")
        return &newDep, fmt.Errorf("pg_restore: %w", err)
    }
    // 3. Apply forward migrations (in case source was on an older schema).
    if err := s.pg.ApplyMigrationsOnly(ctx, &newDep); err != nil { return &newDep, err }
    // 4. Healthz.
    if err := waitForPublicHealth(ctx, &newDep); err != nil { return &newDep, err }
    _ = s.repo.UpdateStatus(ctx, newDep.ID, "active")
    _ = s.events.Publish(ctx, "deployment.restored", "", map[string]any{
        "source_deployment_id": source.ID, "new_deployment_id": newDep.ID, "to_timestamp": toTimestamp,
    })
    return &newDep, nil
}
```

`backupAdapter` interface is implemented by a thin `internal/controlplane/provision/backup/` package that wraps `pg_basebackup` + `pg_restore` shell calls. For MVP, the operator runs a manual nightly logical dump cron (documented in runbook); WAL is cluster-wide so PITR works against any window.

### 12e.8 Purge

`purge.go`:

```go
func (s *Sequence) Purge(ctx context.Context, dep *Deployment) error {
    if dep.Status != "destroyed" && dep.Status != "failed" {
        return ErrCannotPurgeActive
    }
    // Emit the audit row BEFORE the data disappears (§18.6).
    _ = s.events.Publish(ctx, "deployment.purged", "", map[string]any{
        "deployment_id": dep.ID, "purged_at": time.Now(),
    })
    // Now physically drop everything. Order: pods first, then nginx, then DB, then keys.
    if err := s.k3s.Destroy(ctx, dep); err != nil { slog.Warn("purge: k3s", "err", err) }
    if err := s.nginx.RemoveVhost(ctx, dep.ID); err != nil { slog.Warn("purge: nginx", "err", err) }
    if err := s.nginx.DeleteCertificate(ctx, dep.ID); err != nil { slog.Warn("purge: certbot", "err", err) }
    if err := s.pg.Purge(ctx, dep); err != nil { slog.Warn("purge: postgres", "err", err) }
    if err := s.openbao.Purge(ctx, dep); err != nil { slog.Warn("purge: openbao", "err", err) }
    if err := s.repo.UpdateStatus(ctx, dep.ID, "purged"); err != nil { return err }
    return nil
}
```

Each step logs warnings rather than aborting; purge MUST proceed even if individual systems are partially absent (idempotent across multiple invocations).

### 12e.9 FreezeKeys

`freeze.go`:

```go
func (s *Sequence) FreezeKeys(ctx context.Context, dep *Deployment, reason string) error {
    if err := s.openbao.FreezeKeys(ctx, dep.ID); err != nil { return err }
    // Revoke the active k8s auth role token (kills running pods' OpenBao access).
    if err := s.openbao.RevokeTokensForRole(ctx, dep.ID); err != nil { return err }
    if err := s.repo.UpdateStatus(ctx, dep.ID, "frozen"); err != nil { return err }
    _ = s.events.Publish(ctx, "deployment.keys_frozen", "", map[string]any{
        "deployment_id": dep.ID, "reason": reason, "by": auth.ActorIDFromContext(ctx),
    })
    return nil
}
```

Add the OpenAPI surface:

```yaml
  /control/v1/deployments/{deployment_id}/freeze-keys:
    post:
      operationId: freezeDeploymentKeys
      tags: [deployments]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [reason]
              properties:
                reason: { type: string, minLength: 1, maxLength: 256 }
      responses:
        "202": { content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentResponse" } } } }
```

Step-up MFA required to call this (Phase 13 wires the step-up middleware; Phase 12e installs the endpoint).

### 12e.10 §17.4 provisioning tests

`provisioning_test.go`:

| Test | Setup | Assert |
|---|---|---|
| Happy path | Create deployment | All 13 steps `status=done`; deployment status=active; /healthz returns 200; bootstrap API key returned once |
| Partial failure: openbao down | Stop bao mid-provision | status=failed; ledger shows openbao=failed; subsequent steps not started; reconciler rolls back any prior step (none in this case) |
| Partial failure: postgres down | Stop pg after openbao step | status=failed; openbao step rolled back; KV namespace deleted; transit key deleted |
| Partial failure: k3s down | Stop k3s after postgres step | status=failed; postgres rolled back (DB dropped, role dropped); openbao rolled back |
| Partial failure: nginx test fails | Plant a syntax error mid-template | status=failed; vhost file removed; symlink removed; cert NOT issued; k3s ns destroyed; pg DB dropped; bao key purged |
| Upgrade happy | Upgrade from v0.3.1 → v0.3.2 | status flips active→upgrading→active; deployment_revision row added; pods running new image |
| Upgrade with no migrations | run_migrations=false | image flips; DB schema unchanged |
| Upgrade refused (downgrade) | Try v0.3.2 → v0.3.1 | 422 ErrCannotDowngrade |
| Rollback | Rollback after successful upgrade | image flips back; deployment_revision.is_rolled_back=true; DB schema unchanged |
| Restore | Restore to T-1h | new dep_id created; pg_restore happy; status=active; events emitted |
| Restore PITR out of range | Restore to T-100d (older than WAL) | 422 ErrPITROutOfRange |
| Purge from active | Purge an active deployment | 422 ErrCannotPurgeActive |
| Purge from destroyed | Soft-delete then purge | All artifacts gone; status=purged; audit row exists with action='deployment.purged' |
| FreezeKeys | Freeze a key, then attempt to encrypt | Encrypt fails with permission denied; status=frozen |

### 12e.11 saasctl

```text
saasctl deployment provision <project> <env> --image <v>     # alias for create
saasctl deployment upgrade <dep_id> --image <v> [--no-migrations]
saasctl deployment rollback <dep_id>
saasctl deployment restore <dep_id> --to-timestamp <RFC3339>
saasctl deployment purge <dep_id>
saasctl deployment freeze-keys <dep_id> --reason "<text>"
saasctl deployment ledger <dep_id>     # prints the provision_step ledger
```

`saasctl deployment ledger` shows operators the per-step status; critical for diagnosing partial failures.

### 12e.12 ADR (no new one mandated by master)

This phase doesn't create a new ADR; the sequence itself + the destroy reconciler are reflected in ADR 015 (BYOD; touches vhost step) and the existing ADRs cover the rest.

If user wants one for the sequence orchestration design, create `docs/adr/020-provisioning-sequence-orchestration.md` covering: 13-step ledger, per-step idempotency, reverse-rollback, destroy reconciler tick, freeze-keys flow. Confirm with user.

### 12e.13 Commits

```bash
git add migrations/controlplane/000003_provision_step.up.sql internal/controlplane/db/queries/provision_step.sql
git commit -m "add provision step ledger"

git add internal/controlplane/provision/sequence/
git commit -m "implement provisioning sequence with rollback"

git add internal/controlplane/provision/sequence/destroy.go
git commit -m "add destroy reconciler goroutine"

git add internal/controlplane/provision/sequence/upgrade.go internal/controlplane/provision/sequence/rollback.go internal/controlplane/provision/sequence/restore.go internal/controlplane/provision/sequence/purge.go internal/controlplane/provision/sequence/freeze.go
git commit -m "implement upgrade rollback restore purge freeze"

git add internal/controlplane/provision/backup/
git commit -m "add backup adapter for pitr restore"

git add openapi/control-plane.yaml
git commit -m "add freeze keys endpoint"

git add cmd/controlplane/main.go cmd/saasctl/
git commit -m "wire sequence orchestrator and saasctl coverage"
```

---

## Verification checklist

```bash
# 1. Build + lint + tests.
$ make build && make lint && make test && make test-int

# 2. Provision a real deployment end-to-end.
$ ./bin/saasctl deployment create --project finalcheck --environment dev --image v0.3.1
# Expected: Deployment created in ~30s; bootstrap secret printed once.

# 3. Inspect the ledger.
$ ./bin/saasctl deployment ledger <dep_id>
# Expected: 13 rows, all done

# 4. Verify EVERY artifact (the operator's pre-CHECKPOINT-9 review).
$ docker compose exec openbao bao read transit/keys/<dep_id>
$ docker compose exec openbao bao policy read <dep_id>
$ docker compose exec openbao bao read auth/kubernetes/role/<dep_id>
$ docker compose exec openbao bao kv list secret/<dep_id>/
$ psql -l | grep saas_finalcheck_dev
$ psql -c "\du" | grep saas_finalcheck_dev_app
$ psql -d saas_finalcheck_dev -c "\dt app.*"
$ kubectl get ns saas-finalcheck-dev
$ kubectl -n saas-finalcheck-dev get all,networkpolicy
$ ls /etc/nginx/sites-enabled/saas-<dep_id>.conf
$ sudo certbot certificates --cert-name <dep_id>
$ curl -I https://dev.finalcheck.saas.omarss.net/healthz
# Expected: every command shows the artifact in place

# 5. Use the bootstrap API key.
$ SECRET=<from create output>
$ curl https://dev.finalcheck.saas.omarss.net/v1/tenants -H "Authorization: Bearer $SECRET" | jq
# Expected: 200 with the bootstrap tenant

# 6. Partial-failure test (bao down).
$ docker compose stop openbao
$ ./bin/saasctl deployment create --project failtest --environment dev --image v0.3.1
# Expected: status=failed; reconciler attempts rollback (no completed steps, so no-op);
# subsequent re-attempt after bao up succeeds.
$ docker compose start openbao
$ # Wait 30s for reconciler; or:
$ ./bin/saasctl deployment ledger <dep_id_failed>
$ # If status=destroyed via reconciler, the ledger shows openbao step still failed but the row goes away.

# 7. Upgrade.
$ ./bin/saasctl deployment upgrade <dep_id> --image v0.3.2
$ ./bin/saasctl deployment get <dep_id> | jq .image_version
# Expected: v0.3.2

# 8. Rollback.
$ ./bin/saasctl deployment rollback <dep_id>
$ ./bin/saasctl deployment get <dep_id> | jq .image_version
# Expected: v0.3.1

# 9. Restore (requires WAL archive set up; otherwise: 422).
$ ./bin/saasctl deployment restore <dep_id> --to-timestamp "$(date -d '5 minutes ago' --rfc-3339=seconds)"
# Expected: new dep_id; status=active; pg_restore happy

# 10. Purge.
$ ./bin/saasctl deployment delete <dep_id> --retain-days 0
$ ./bin/saasctl deployment purge <dep_id>
# Expected: every artifact removed (re-verify the checks from step 4 — all empty)

# 11. FreezeKeys.
$ ./bin/saasctl deployment freeze-keys <dep_id> --reason "phase 12e demo"
$ # Subsequent encrypt via the data-plane pod fails.
$ kubectl -n saas-<...> logs deploy/data-plane | grep "encrypt fail"
# Expected: 403 permission denied; status=frozen

# 12. §17.4 full matrix.
$ go test -run TestProvisioning -v ./internal/controlplane/provision/sequence/...
# Expected: all 14 cases green
```

---

## Anti-pattern guards

- **NEVER** skip the rollback on partial failure. Operator pain compounds; the destroy reconciler should not have to undo half-states the orchestrator didn't try to clean.
- **NEVER** allow a downgrade. SemVer compare in Upgrade refuses; bypass requires a manual SQL UPDATE which is an operator-pain trip-wire.
- **NEVER** restore in-place. Restore always creates a NEW deployment_id so the original is preserved for forensics.
- **NEVER** purge an active deployment. The state machine refuses; operators must soft-destroy first.
- **NEVER** emit `deployment.purged` AFTER the data is gone. The audit chain must include the row to remain verifiable.
- **NEVER** block on a step longer than `stepTimeout`. The orchestrator cancels and marks failed; the reconciler can retry.
- **NEVER** allow concurrent provisioning of the same `(project, environment)` slug pair. The DB UNIQUE constraint catches; the handler must surface 409.
- **NEVER** mutate the ledger from outside the orchestrator. The reconciler reads only; the handler reads only.
- **NEVER** call `FreezeKeys` without step-up MFA (Phase 13 wires; until then, restrict to a specific operator scope `deployment.freeze`).
- **NEVER** trust client-supplied `image_version` strings without validating shape (`^v\d+\.\d+\.\d+(-\w+)?$`).

---

## Open questions

1. **Image registry mirror for production.** Local registry works for homelab. Production operators need to configure their own registry. Document in runbook.
2. **WAL retention window.** Default: 7 days. Configurable via `archive_command` retention. Documented in runbook.
3. **Logical dump cadence.** Default: nightly per-Deployment `pg_dump` retained 14 days. systemd timer documented.
4. **Reconciler scale.** Single replica MVP. When scale lands, only one leader-elected reconciler runs (Kubernetes Lease) — out of MVP.
5. **Should freeze auto-thaw after N days?** Default: no. Operators decide. Add to v1.

---

## Phase 12e — Definition of done

- [ ] `migrations/controlplane/000003_provision_step.up.sql` applied
- [ ] `internal/controlplane/provision/sequence/` complete with orchestrator, steps, ledger, destroy reconciler, upgrade, rollback, restore, purge, freeze + tests
- [ ] 13-step sequence ordered per §6.2; ledger records each step
- [ ] Partial failure rolls back completed steps in reverse
- [ ] Destroy reconciler ticks every 30s; handles failed AND soft-deleted-expired
- [ ] Upgrade applies pending migrations + image patch + rollout wait
- [ ] Rollback flips image only; DB untouched
- [ ] Restore creates a new deployment_id with pg_restore + WAL replay
- [ ] Purge emits audit row BEFORE physical delete
- [ ] FreezeKeys disables transit + revokes auth role tokens + sets status=frozen
- [ ] `/control/v1/deployments/{id}/freeze-keys` endpoint added
- [ ] saasctl ledger / upgrade / rollback / restore / purge / freeze-keys
- [ ] §17.4 full matrix (14 cases) passes
- [ ] All Phase 2-12d tests still green
- [ ] PR template, `ready` label, CI green

---

## CHECKPOINT 9 — First end-to-end real Deployment

> The biggest checkpoint. The user inspects EVERY artifact before declaring §15 item #1 done.

### What was done
- migrations/controlplane/000003_provision_step.up.sql
- internal/controlplane/provision/sequence/ (orchestrator, steps, ledger, destroy reconciler, upgrade, rollback, restore, purge, freeze + tests)
- internal/controlplane/provision/backup/ (pg_basebackup + pg_restore wrapper)
- openapi/control-plane.yaml extended with /freeze-keys endpoint
- cmd/controlplane/main.go wired the orchestrator + reconciler
- saasctl: ledger, upgrade, rollback, restore, purge, freeze-keys commands
- §17.4 provisioning matrix (14 tests) passing

### What to verify (user runs these — full provisioning artifact tour)
```bash
# Provision
$ ./bin/saasctl deployment create --project mvp --environment prod --image v0.3.1
$ ./bin/saasctl deployment ledger <dep_id>     # 13 steps, all done

# OpenBao
$ docker compose exec openbao bao read transit/keys/<dep_id>
$ docker compose exec openbao bao policy read <dep_id>
$ docker compose exec openbao bao read auth/kubernetes/role/<dep_id>
$ docker compose exec openbao bao kv list secret/<dep_id>/
$ docker compose exec openbao tail /openbao/logs/audit.log | grep "<dep_id>"

# Postgres
$ psql -l | grep saas_mvp_prod
$ psql -c "\du" | grep saas_mvp_prod_app
$ psql -d saas_mvp_prod -c "SELECT relname, relforcerowsecurity FROM pg_class WHERE relkind='r' ORDER BY relname;"
$ psql -d saas_mvp_prod -c "SET ROLE saas_mvp_prod_app; UPDATE audit_event SET action='x' WHERE 1=1;"     # permission denied

# k3s
$ kubectl get ns saas-mvp-prod -o jsonpath='{.metadata.labels}'
$ kubectl -n saas-mvp-prod get all,networkpolicy,sa
$ kubectl -n saas-mvp-prod logs deploy/data-plane | grep "ready"

# nginx + certbot
$ ls -la /etc/nginx/sites-{available,enabled}/saas-<dep_id>.conf
$ sudo certbot certificates --cert-name <dep_id>

# Public traffic
$ curl -I https://prod.mvp.saas.omarss.net/healthz
$ curl https://prod.mvp.saas.omarss.net/v1/tenants -H "Authorization: Bearer $BOOTSTRAP_SECRET" | jq
$ # End-to-end: create a tenant via API, observe audit row in the data-plane DB
$ curl -X POST https://prod.mvp.saas.omarss.net/v1/tenants \
    -H "Authorization: Bearer $BOOTSTRAP_SECRET" -H "Idempotency-Key: idem_..." \
    -H "Content-Type: application/json" -d '{"slug":"acme","name":"Acme"}'
$ psql -d saas_mvp_prod -c "SELECT action FROM audit_event ORDER BY chain_sequence DESC LIMIT 1;"
$ # Expected: action='tenant.created'

# Control-plane audit
$ psql -d saas_controlplane -c "SELECT action, deployment_id FROM control_plane_audit_event ORDER BY chain_sequence DESC LIMIT 5;"

# Cross-deployment isolation (the central platform promise)
$ ./bin/saasctl deployment create --project mvp --environment dev --image v0.3.1
$ kubectl -n saas-mvp-prod run probe --rm -i --restart=Never --image=curlimages/curl -- \
    curl --max-time 3 -sf http://data-plane.saas-mvp-dev.svc.cluster.local:8080/healthz
# Expected: timeout (NetworkPolicy blocks)

# Upgrade / rollback / freeze / purge — all from CLI
$ ./bin/saasctl deployment upgrade <dep_id> --image v0.3.2
$ ./bin/saasctl deployment rollback <dep_id>
$ ./bin/saasctl deployment freeze-keys <dep_id> --reason demo
$ ./bin/saasctl deployment delete <dep_id> --retain-days 0
$ ./bin/saasctl deployment purge <dep_id>

# Verify purge removed everything
$ docker compose exec openbao bao read transit/keys/<dep_id>     # not found
$ psql -l | grep saas_mvp_prod                                    # not found
$ kubectl get ns saas-mvp-prod                                    # not found
$ ls /etc/nginx/sites-enabled/saas-<dep_id>.conf                  # not found
$ sudo certbot certificates --cert-name <dep_id>                  # not found
```

### What approval means
By proceeding past CHECKPOINT 9, you accept:
- The §15 item #1 (Identity, Tenancy, RBAC, API keys, Audit, Notifications, Social login, BYOD, easy setup, OpenBao) is DONE for the homelab single-host deployment model.
- All host writes are well-bounded: `/etc/nginx/sites-{available,enabled}/saas-*`, k3s namespaces `saas-*`, host Postgres databases prefixed `saas_`, host Postgres roles suffixed `_app`, OpenBao transit keys prefixed `dep_`, KV paths under `secret/dep_*`, sudoers at `/etc/sudoers.d/saas-controlplane`.
- Cross-Deployment isolation is verified at all 8 layers of the §18.1 model.
- Phase 13 onward focuses on operator MFA, Go SDK, DX polish, final verification. Nothing more touches the host writes.

### Rollback if rejected
This is a hard rollback; the §15 item #1 is not achievable without Phase 12e. Reverting means going back to local-mode provisioning (Phase 11). Discuss with user before reverting.

```bash
# Full revert chain (last-ditch).
$ ./bin/saasctl deployment purge <each_dep_id>     # clean up everything provisioned
$ git revert <hashes for the 8 phase-12e commits>
```

---

End of Phase 12e. Next: `14-impersonation-operator-mfa.md`.
