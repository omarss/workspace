package sequence

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"github.com/omarss/saas/internal/controlplane/deployments"
)

// DestroyRepo is the narrow port the reconciler uses to discover
// deployments needing cleanup. Satisfied by deployments.Repository
// via a small adapter (see deployments.RepoForReconciler in
// internal/controlplane/deployments/repo_reconciler.go if we ever wire
// the pgx repo; for MVP the in-memory fake in test_support.go covers
// the test path).
type DestroyRepo interface {
	// ListByStatus returns up to `limit` deployments matching any of
	// the provided statuses, ORDERED BY updated_at ASC (oldest first
	// so a stuck deployment that fails the rollback chain gets
	// retried on every tick until it's escalated).
	ListByStatus(ctx context.Context, statuses []deployments.Status, limit int) ([]deployments.Deployment, error)

	// UpdateStatus moves a deployment's status. Used to flip
	// 'failed' → 'destroyed' after a successful rollback, and
	// 'destroyed' → 'purged' after physical purge.
	UpdateStatus(ctx context.Context, id string, status deployments.Status) error

	// ListExpiredSoftDeletes returns 'destroyed' rows whose
	// retain_until has passed. Empty if retention is disabled.
	ListExpiredSoftDeletes(ctx context.Context, now time.Time, limit int) ([]deployments.Deployment, error)
}

// DestroyReconciler is the goroutine that drives partial-failure
// cleanup + retention-expired purge. Started by cmd/controlplane and
// runs for the lifetime of the process.
type DestroyReconciler struct {
	Repo     DestroyRepo
	Sequence *Sequence

	// Adapters lets the reconciler invoke the lifecycle flows (Purge
	// in particular) without re-creating Step closures.
	Adapters Adapters

	// Events publishes deployment.destroyed + .purged events to the
	// outbox after a successful reconciliation step. Defaults to a
	// no-op if nil.
	Events EventPublisher

	// Period is the tick interval. Default 30 s.
	Period time.Duration

	// Batch is the per-tick scan limit. Default 10 deployments.
	Batch int

	// Logger; defaults to slog.Default().
	Logger *slog.Logger
}

// Run blocks until ctx is cancelled. Ticks every `Period`; on each
// tick, scans for `'failed'` and `'destroying'` deployments and runs
// the rollback / destroy flow against them, then scans for retention-
// expired `'destroyed'` deployments and physically purges them.
//
// All failures inside a tick are LOGGED but do not abort the
// reconciler's lifetime — a transient adapter outage should not
// kill the goroutine.
func (r *DestroyReconciler) Run(ctx context.Context) error {
	if r.Logger == nil {
		r.Logger = slog.Default()
	}
	if r.Period <= 0 {
		r.Period = 30 * time.Second
	}
	if r.Batch <= 0 {
		r.Batch = 10
	}
	if r.Repo == nil || r.Sequence == nil {
		return errors.New("reconciler: repo + sequence required")
	}

	t := time.NewTicker(r.Period)
	defer t.Stop()
	// Tick once immediately so a freshly-started reconciler doesn't
	// wait `Period` before doing useful work.
	r.tick(ctx)
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-t.C:
			r.tick(ctx)
		}
	}
}

// tick is one reconciliation pass. Split out from Run so tests can
// exercise the logic without a goroutine.
func (r *DestroyReconciler) tick(ctx context.Context) {
	// 1. Failed deployments → roll back completed steps; flip to
	//    'destroyed' on success.
	failed, err := r.Repo.ListByStatus(ctx, []deployments.Status{
		deployments.StatusFailed,
	}, r.Batch)
	if err != nil {
		r.Logger.Error("reconciler: list failed", "err", err)
	}
	for _, d := range failed {
		r.handleFailed(ctx, &d)
	}

	// 2. Destroying deployments → full teardown regardless of step
	//    state; flip to 'destroyed' on success.
	destroying, err := r.Repo.ListByStatus(ctx, []deployments.Status{
		deployments.StatusDestroying,
	}, r.Batch)
	if err != nil {
		r.Logger.Error("reconciler: list destroying", "err", err)
	}
	for _, d := range destroying {
		r.handleDestroying(ctx, &d)
	}

	// 3. Purging deployments → physical purge; bypass retention.
	purging, err := r.Repo.ListByStatus(ctx, []deployments.Status{
		deployments.StatusPurging,
	}, r.Batch)
	if err != nil {
		r.Logger.Error("reconciler: list purging", "err", err)
	}
	for _, d := range purging {
		r.handlePurging(ctx, &d)
	}

	// 4. Retention-expired soft-deletes → physical purge.
	expired, err := r.Repo.ListExpiredSoftDeletes(ctx, time.Now().UTC(), r.Batch)
	if err != nil {
		r.Logger.Error("reconciler: list expired", "err", err)
	}
	for _, d := range expired {
		r.handlePurging(ctx, &d)
	}
}

// handleFailed runs the rollback chain for a failed provisioning.
// Success flips status to 'destroyed'; failure leaves the row in
// 'failed' so the next tick retries.
func (r *DestroyReconciler) handleFailed(ctx context.Context, d *deployments.Deployment) {
	r.Logger.Info("reconciler: rolling back failed deployment", "deployment_id", d.ID)
	dep := FromDeployment(d)
	if err := r.Sequence.RollbackCompleted(ctx, dep); err != nil {
		r.Logger.Error("reconciler: rollback failed; will retry",
			"deployment_id", d.ID, "err", err)
		return
	}
	if err := r.Repo.UpdateStatus(ctx, d.ID, deployments.StatusDestroyed); err != nil {
		r.Logger.Error("reconciler: status update after rollback",
			"deployment_id", d.ID, "err", err)
		return
	}
	if r.Events != nil {
		_ = r.Events.Publish(ctx, "deployment.destroyed", d.ID, map[string]any{
			"deployment_id": d.ID,
			"reason":        "provisioning_failed",
		})
	}
}

// handleDestroying tears down EVERYTHING regardless of step state.
// Used when the operator soft-deleted an active deployment — we run
// the full purge sequence + flip status to 'destroyed' on success.
func (r *DestroyReconciler) handleDestroying(ctx context.Context, d *deployments.Deployment) {
	r.Logger.Info("reconciler: destroying deployment", "deployment_id", d.ID)
	dep := FromDeployment(d)
	if err := destroyAllAdapters(ctx, dep, r.Adapters, r.Logger); err != nil {
		r.Logger.Error("reconciler: destroy failed; will retry",
			"deployment_id", d.ID, "err", err)
		return
	}
	if err := r.Repo.UpdateStatus(ctx, d.ID, deployments.StatusDestroyed); err != nil {
		r.Logger.Error("reconciler: status update after destroy",
			"deployment_id", d.ID, "err", err)
		return
	}
	if r.Events != nil {
		_ = r.Events.Publish(ctx, "deployment.destroyed", d.ID, map[string]any{
			"deployment_id": d.ID,
			"reason":        "operator_requested",
		})
	}
}

// handlePurging physically deletes everything. Symmetric to
// handleDestroying but flips to 'purged' (vs 'destroyed') so the row
// stays in the control-plane DB as a forensic record while every
// downstream artifact is gone.
func (r *DestroyReconciler) handlePurging(ctx context.Context, d *deployments.Deployment) {
	r.Logger.Info("reconciler: purging deployment", "deployment_id", d.ID)
	// Emit the audit row BEFORE the data disappears (§18.6).
	if r.Events != nil {
		_ = r.Events.Publish(ctx, "deployment.purged", d.ID, map[string]any{
			"deployment_id": d.ID,
			"purged_at":     time.Now().UTC().Format(time.RFC3339),
		})
	}
	dep := FromDeployment(d)
	if err := destroyAllAdapters(ctx, dep, r.Adapters, r.Logger); err != nil {
		r.Logger.Error("reconciler: purge failed; will retry",
			"deployment_id", d.ID, "err", err)
		return
	}
	if err := r.Repo.UpdateStatus(ctx, d.ID, deployments.StatusPurged); err != nil {
		r.Logger.Error("reconciler: status update after purge",
			"deployment_id", d.ID, "err", err)
		return
	}
}
