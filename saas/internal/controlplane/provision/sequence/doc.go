// Package sequence composes the four per-Deployment host adapters
// (nginx + k3s + postgres + openbao) into the AGENTS.md §6.2 13-step
// provisioning sequence + a destroy reconciler + the §6.3 upgrade /
// rollback / restart and §6.6 restore / §18.6 purge / §18.7 freeze-keys
// lifecycle flows.
//
// Phase 12a-d shipped each adapter in isolation behind `saasctl debug
// <adapter> apply|remove` helpers so CHECKPOINT 5/6/7/8 could verify
// the host writes one layer at a time. Phase 12e (this package) glues
// them together — the debug subcommands are removed because the full
// `saasctl deployment` surface now drives the same code path through
// the production HostProvisioner.
//
// # Ordering
//
// The 13 §6.2 steps are realised by Step values with explicit Run +
// Rollback callbacks. The orchestrator records each step's status in
// the control-plane DB (`deployment_provision_step` table, shipped in
// migration 000002) so a partial failure is observable + recoverable.
//
// Step ordering respects all phase dependencies:
//
//  1. validate         — slugs (handler already enforced)
//  2. allocate_id      — dep_<ulid>
//  3. record_state     — INSERT deployment + provision_step rows
//  4. openbao          — transit key + policy + k8s role + KV path
//     (must precede postgres so the pg password
//     has a place to live)
//  5. postgres         — CREATE DB + role + grants + migrations + RLS
//  6. seed             — bootstrap tenant + admin + API key
//  7. render_k3s       — kustomize render to bytes
//  8. k3s_apply        — SSA + WaitReady
//  9. render_nginx     — vhost template render
//  10. nginx_apply      — install + nginx -t + reload + certbot
//  11. healthz          — poll https://<vhost>/healthz until 200
//  12. flip_active      — status=active + deployment.provisioned event
//  13. return_bootstrap — handler captures from the ledger
//
// # Rollback on partial failure
//
// On a step failure, the orchestrator runs the Rollback callback for
// each previously completed step IN REVERSE ORDER. Failures during
// rollback escalate the deployment to status='corrupted' so the
// operator can inspect; the destroy reconciler then retries the
// rollback with a longer back-off.
//
// # Destroy reconciler
//
// `DestroyReconciler.Run` is a goroutine started by cmd/controlplane.
// Every 30s it scans:
//
//   - `status='failed'`: walk completed provision_step rows in reverse
//     and run their Rollback callbacks. On success → status='destroyed'.
//   - `status='destroying'`: full teardown regardless of step state.
//     On success → status='destroyed'.
//   - `status='destroyed' AND retain_until < now()`: physical purge.
//     On success → status='purged'.
//   - `status='purging'`: bypass retention, run purge immediately.
//
// # Lifecycle flows
//
// Upgrade  (§6.3): semver-validated forward-only migration + image
// patch + WaitReady + healthz. DB is NOT rolled back on rollback (§27
// enforces backward-compatible migrations).
//
// Rollback (§6.3): image flip only, DB untouched.
//
// Restart  (no AGENTS spec): `kubectl rollout restart` + WaitReady.
//
// Restore  (§6.6): creates a NEW deployment_id; provisions normally
// but replaces the migration step with pg_restore + WAL replay to
// the requested PITR timestamp.
//
// Purge    (§18.6): bypass retention, tear down everything, optionally
// physical-delete the control-plane rows. Audit row is emitted BEFORE
// the data disappears so the chain remains verifiable.
//
// FreezeKeys (§18.7): set the transit key's min_decryption_version to
// a high value (effectively unusable) + revoke active k8s auth role
// tokens + status='frozen'. Reversible by an operator with step-up
// auth (Phase 13).
//
// # Backup adapter
//
// Phase 12e ships a `backup` sub-package as a stub: the real
// pg_basebackup + pg_restore + WAL replay flow needs host-level setup
// (WAL archiving configured on the cluster) that is out of MVP. The
// stub returns ErrNotImplemented on RestoreToNewDB; the operator runs
// the actual `pg_restore` manually for MVP and the platform records
// the restored deployment row.
package sequence
