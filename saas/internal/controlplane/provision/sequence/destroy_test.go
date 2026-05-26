package sequence_test

import (
	"context"
	"testing"
	"time"

	"github.com/omarss/saas/internal/controlplane/deployments"
	"github.com/omarss/saas/internal/controlplane/provision/sequence"
)

// fakeDestroyRepo is the in-memory DestroyRepo used by the reconciler
// tests. It maintains a small slice of deployments keyed by status.
type fakeDestroyRepo struct {
	byID map[string]*deployments.Deployment
}

func newFakeDestroyRepo() *fakeDestroyRepo {
	return &fakeDestroyRepo{byID: map[string]*deployments.Deployment{}}
}

func (f *fakeDestroyRepo) add(d *deployments.Deployment) { f.byID[d.ID] = d }

func (f *fakeDestroyRepo) ListByStatus(_ context.Context, statuses []deployments.Status, _ int) ([]deployments.Deployment, error) {
	var out []deployments.Deployment
	for _, d := range f.byID {
		for _, s := range statuses {
			if d.Status == s {
				out = append(out, *d)
				break
			}
		}
	}
	return out, nil
}

func (f *fakeDestroyRepo) UpdateStatus(_ context.Context, id string, status deployments.Status) error {
	if d, ok := f.byID[id]; ok {
		d.Status = status
	}
	return nil
}

func (f *fakeDestroyRepo) ListExpiredSoftDeletes(_ context.Context, _ time.Time, _ int) ([]deployments.Deployment, error) {
	return nil, nil
}

func TestReconciler_RollsBackFailedDeployment(t *testing.T) {
	ledger := sequence.NewMemoryLedger()
	var log []string
	seq := &sequence.Sequence{
		Ledger: ledger,
		Steps: []sequence.Step{
			stubStep("a", &log, false),
			stubStep("b", &log, false),
		},
	}
	ctx := context.Background()
	// Simulate a previously-completed run by populating the ledger.
	for _, n := range []string{"a", "b"} {
		_ = ledger.Start(ctx, "dep_X", n)
		_ = ledger.Done(ctx, "dep_X", n)
	}
	repo := newFakeDestroyRepo()
	repo.add(&deployments.Deployment{ID: "dep_X", Status: deployments.StatusFailed})

	rec := &sequence.DestroyReconciler{
		Repo:     repo,
		Sequence: seq,
		Period:   time.Hour, // disables the ticker; we call tick manually via Run+cancel
	}

	tickCtx, cancel := context.WithTimeout(ctx, 100*time.Millisecond)
	defer cancel()
	// Run executes one immediate tick before waiting for the ticker.
	_ = rec.Run(tickCtx)

	if repo.byID["dep_X"].Status != deployments.StatusDestroyed {
		t.Errorf("expected destroyed; got %s", repo.byID["dep_X"].Status)
	}
	wantPrefix := []string{"rollback:b", "rollback:a"}
	for i := range wantPrefix {
		if log[i] != wantPrefix[i] {
			t.Errorf("log[%d]=%q; want %q", i, log[i], wantPrefix[i])
		}
	}
}
