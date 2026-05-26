package sequence

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/omarss/saas/internal/controlplane/deployments"
)

// Step is one entry in the §6.2 13-step sequence. Each step records its
// completion in the ledger; Rollback runs (in reverse order) when a
// later step fails OR when the destroy reconciler picks up the
// deployment for cleanup.
//
// Run + Rollback are SEPARATE closures (not methods on a Step type) so
// the orchestrator can compose adapters without making them aware of
// each other — the nginx step's Rollback closes over the nginx adapter
// only.
//
// Timeout is per-step; the orchestrator wraps Run in
// context.WithTimeout(parent, Timeout). 0 means "use the orchestrator
// default" (10 minutes — wide enough for the slowest step, k3s_apply,
// which inherits its own 5 min internal poll).
type Step struct {
	Name     string
	Timeout  time.Duration
	Run      func(ctx context.Context, dep DeploymentRef) error
	Rollback func(ctx context.Context, dep DeploymentRef) error
}

// defaultStepTimeout is the per-step wall-clock cap when Step.Timeout
// is zero. 10 minutes is the sum of the longest realistic adapter
// internal timeout (k3s rollout 5 min) + nginx/cert 2 min + slack.
const defaultStepTimeout = 10 * time.Minute

// Sequence is the orchestrator. The four adapters are injected via the
// HostProvisioner that builds the steps; the orchestrator itself is
// agnostic to which adapter a step talks to.
type Sequence struct {
	Steps  []Step
	Ledger Ledger
	Logger *slog.Logger
}

// Run executes every step in order. On a step failure:
//
//  1. Mark the step 'failed' in the ledger.
//  2. Call rollbackInReverse on the previously-completed steps. Any
//     rollback failure is logged but does NOT abort the rollback chain;
//     the destroy reconciler retries with longer back-off.
//  3. Return the wrapped step error so the caller (HostProvisioner)
//     can flip the deployment's status to 'failed'.
//
// Idempotency: an already-completed step (marked by a previous Run
// attempt) is skipped via the ledger's Start no-op contract — the
// callback is NOT re-invoked. This means retrying Run on a partially-
// completed deployment resumes from the first non-completed step.
func (s *Sequence) Run(ctx context.Context, dep DeploymentRef) error {
	if s.Logger == nil {
		s.Logger = slog.Default()
	}
	if s.Ledger == nil {
		return fmt.Errorf("%w: ledger not configured", ErrAdapterNil)
	}

	completedThisRun := make([]int, 0, len(s.Steps))
	for i, step := range s.Steps {
		// Check if this step is already done from a prior run. We use
		// the public List API because Start's idempotent no-op contract
		// returns nil — we have to know BEFORE calling Run whether to
		// skip the callback entirely.
		if s.stepAlreadyCompleted(ctx, dep.ID, step.Name) {
			s.Logger.Info("sequence: step already completed; skipping",
				"deployment_id", dep.ID, "step", step.Name)
			continue
		}

		if err := s.Ledger.Start(ctx, dep.ID, step.Name); err != nil {
			return fmt.Errorf("ledger.Start(%s): %w", step.Name, err)
		}

		runErr := s.runStep(ctx, step, dep)
		if runErr != nil {
			_ = s.Ledger.Fail(ctx, dep.ID, step.Name, runErr)
			s.Logger.Error("sequence: step failed; rolling back",
				"deployment_id", dep.ID, "step", step.Name, "err", runErr)
			s.rollbackInReverse(ctx, dep, completedThisRun)
			return fmt.Errorf("%w: %s: %w", ErrStepFailed, step.Name, runErr)
		}
		if err := s.Ledger.Done(ctx, dep.ID, step.Name); err != nil {
			return fmt.Errorf("ledger.Done(%s): %w", step.Name, err)
		}
		completedThisRun = append(completedThisRun, i)
	}
	return nil
}

// runStep wraps a step's Run callback in a per-step timeout. A nil
// callback is treated as a no-op (used by the "validate" and similar
// metadata-only steps).
func (s *Sequence) runStep(ctx context.Context, step Step, dep DeploymentRef) error {
	if step.Run == nil {
		return nil
	}
	timeout := step.Timeout
	if timeout <= 0 {
		timeout = defaultStepTimeout
	}
	runCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	return step.Run(runCtx, dep)
}

// stepAlreadyCompleted reads the ledger to find out whether (dep, step)
// is already 'completed'. Returns false on any error (defensive — the
// caller will Start the step anyway, and re-running an already-done
// adapter operation is safe because every adapter is idempotent).
func (s *Sequence) stepAlreadyCompleted(ctx context.Context, deploymentID, stepName string) bool {
	rows, err := s.Ledger.List(ctx, deploymentID)
	if err != nil {
		return false
	}
	for _, r := range rows {
		if r.StepName == stepName && r.Status == LedgerStatusCompleted {
			return true
		}
	}
	return false
}

// rollbackInReverse walks the supplied indices LATEST FIRST and calls
// each step's Rollback. A nil Rollback callback is skipped. Failures
// are LOGGED but the chain continues — the destroy reconciler retries
// with a longer back-off and may eventually escalate to 'corrupted'
// status if rollback keeps failing.
//
// A detached parent context is used so that cleanup proceeds even
// when the original ctx is already cancelled (timeout reached, signal
// received). Bounded with a generous timeout to prevent the goroutine
// from hanging forever on a stuck adapter.
func (s *Sequence) rollbackInReverse(_ context.Context, dep DeploymentRef, indices []int) {
	rollbackParent, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()
	for i := len(indices) - 1; i >= 0; i-- {
		step := s.Steps[indices[i]]
		if step.Rollback == nil {
			_ = s.Ledger.RolledBack(rollbackParent, dep.ID, step.Name)
			continue
		}
		timeout := step.Timeout
		if timeout <= 0 {
			timeout = defaultStepTimeout
		}
		rbCtx, cancelStep := context.WithTimeout(rollbackParent, timeout)
		err := step.Rollback(rbCtx, dep)
		cancelStep()
		if err != nil {
			s.Logger.Error("sequence: rollback failed",
				"deployment_id", dep.ID, "step", step.Name, "err", err)
			// Leave the ledger entry as 'completed' so the destroy
			// reconciler picks it up again on its next tick. Do NOT
			// transition to 'rolled_back' on a failure.
			continue
		}
		_ = s.Ledger.RolledBack(rollbackParent, dep.ID, step.Name)
	}
}

// RollbackCompleted is the entry point for the destroy reconciler.
// Walks every 'completed' ledger row for the deployment LATEST FIRST
// and invokes its step's Rollback. Symmetric to rollbackInReverse but
// uses the ledger as the source of truth (not the in-memory list of
// indices) so it works after a process restart.
func (s *Sequence) RollbackCompleted(ctx context.Context, dep DeploymentRef) error {
	rows, err := s.Ledger.ListCompletedReverse(ctx, dep.ID)
	if err != nil {
		return fmt.Errorf("ledger.ListCompletedReverse: %w", err)
	}
	stepByName := make(map[string]Step, len(s.Steps))
	for _, st := range s.Steps {
		stepByName[st.Name] = st
	}
	var failures []string
	for _, row := range rows {
		step, ok := stepByName[row.StepName]
		if !ok {
			// Step name from an older release; nothing to roll back.
			continue
		}
		if step.Rollback == nil {
			_ = s.Ledger.RolledBack(ctx, dep.ID, step.Name)
			continue
		}
		timeout := step.Timeout
		if timeout <= 0 {
			timeout = defaultStepTimeout
		}
		rbCtx, cancel := context.WithTimeout(ctx, timeout)
		err := step.Rollback(rbCtx, dep)
		cancel()
		if err != nil {
			failures = append(failures, fmt.Sprintf("%s: %v", step.Name, err))
			continue
		}
		_ = s.Ledger.RolledBack(ctx, dep.ID, step.Name)
	}
	if len(failures) > 0 {
		return fmt.Errorf("%w: %v", ErrRollbackFailed, failures)
	}
	return nil
}

// MapDeploymentStatus translates a Sequence outcome into the matching
// deployments.Status. Callers (HostProvisioner) use this so the
// orchestrator's vocabulary stays decoupled from the resource model's
// state-machine enum.
func MapDeploymentStatus(success bool, err error) deployments.Status {
	if err == nil && success {
		return deployments.StatusActive
	}
	if errors.Is(err, ErrRollbackFailed) {
		// 'corrupted' was the planned escalation state, but the
		// existing migration's CHECK constraint does not include it
		// (the canonical enum tops out at 'purged'). Fall back to
		// 'failed' and rely on the destroy reconciler to keep trying
		// with longer back-off; an operator escalation is a manual
		// SQL UPDATE for MVP.
		return deployments.StatusFailed
	}
	return deployments.StatusFailed
}
