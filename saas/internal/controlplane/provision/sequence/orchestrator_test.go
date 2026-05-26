package sequence_test

import (
	"context"
	"errors"
	"slices"
	"testing"
	"time"

	"github.com/omarss/saas/internal/controlplane/deployments"
	"github.com/omarss/saas/internal/controlplane/provision/sequence"
)

// stubStep returns a step that records its invocation order in a
// shared slice. fail=true makes its Run return an error; rollback=true
// records a rollback call.
func stubStep(name string, log *[]string, fail bool) sequence.Step {
	return sequence.Step{
		Name:    name,
		Timeout: 5 * time.Second,
		Run: func(_ context.Context, _ sequence.DeploymentRef) error {
			*log = append(*log, "run:"+name)
			if fail {
				return errors.New("boom")
			}
			return nil
		},
		Rollback: func(_ context.Context, _ sequence.DeploymentRef) error {
			*log = append(*log, "rollback:"+name)
			return nil
		},
	}
}

func TestSequence_HappyPath(t *testing.T) {
	var log []string
	s := &sequence.Sequence{
		Ledger: sequence.NewMemoryLedger(),
		Steps: []sequence.Step{
			stubStep("a", &log, false),
			stubStep("b", &log, false),
			stubStep("c", &log, false),
		},
	}
	dep := sequence.DeploymentRef{ID: "dep_test"}
	if err := s.Run(context.Background(), dep); err != nil {
		t.Fatalf("Run: %v", err)
	}
	want := []string{"run:a", "run:b", "run:c"}
	if !equalSlice(log, want) {
		t.Errorf("got log %v; want %v", log, want)
	}
}

func TestSequence_RollsBackInReverseOnFailure(t *testing.T) {
	var log []string
	s := &sequence.Sequence{
		Ledger: sequence.NewMemoryLedger(),
		Steps: []sequence.Step{
			stubStep("a", &log, false),
			stubStep("b", &log, false),
			stubStep("c", &log, true), // fails
		},
	}
	dep := sequence.DeploymentRef{ID: "dep_test"}
	err := s.Run(context.Background(), dep)
	if err == nil {
		t.Fatalf("expected error")
	}
	if !errors.Is(err, sequence.ErrStepFailed) {
		t.Errorf("expected ErrStepFailed; got %v", err)
	}
	// Order: run:a, run:b, run:c, rollback:b, rollback:a.
	want := []string{"run:a", "run:b", "run:c", "rollback:b", "rollback:a"}
	if !equalSlice(log, want) {
		t.Errorf("got log %v; want %v", log, want)
	}
}

func TestSequence_IdempotentResume(t *testing.T) {
	// Pre-populate the ledger so steps a + b are already completed.
	ledger := sequence.NewMemoryLedger()
	ctx := context.Background()
	for _, n := range []string{"a", "b"} {
		_ = ledger.Start(ctx, "dep_test", n)
		_ = ledger.Done(ctx, "dep_test", n)
	}
	var log []string
	s := &sequence.Sequence{
		Ledger: ledger,
		Steps: []sequence.Step{
			stubStep("a", &log, false),
			stubStep("b", &log, false),
			stubStep("c", &log, false),
		},
	}
	if err := s.Run(ctx, sequence.DeploymentRef{ID: "dep_test"}); err != nil {
		t.Fatalf("Run: %v", err)
	}
	// Only c should be executed.
	want := []string{"run:c"}
	if !equalSlice(log, want) {
		t.Errorf("got %v; want %v", log, want)
	}
}

func TestSequence_RollbackCompleted_WalksReverse(t *testing.T) {
	ledger := sequence.NewMemoryLedger()
	var log []string
	s := &sequence.Sequence{
		Ledger: ledger,
		Steps: []sequence.Step{
			stubStep("a", &log, false),
			stubStep("b", &log, false),
			stubStep("c", &log, false),
		},
	}
	ctx := context.Background()
	dep := sequence.DeploymentRef{ID: "dep_test"}
	if err := s.Run(ctx, dep); err != nil {
		t.Fatalf("Run: %v", err)
	}
	log = log[:0]
	if err := s.RollbackCompleted(ctx, dep); err != nil {
		t.Fatalf("RollbackCompleted: %v", err)
	}
	want := []string{"rollback:c", "rollback:b", "rollback:a"}
	if !equalSlice(log, want) {
		t.Errorf("got %v; want %v", log, want)
	}
}

func TestSequence_LedgerRecordsStepStatus(t *testing.T) {
	ledger := sequence.NewMemoryLedger()
	var log []string
	s := &sequence.Sequence{
		Ledger: ledger,
		Steps: []sequence.Step{
			stubStep("a", &log, false),
			stubStep("b", &log, true),
		},
	}
	ctx := context.Background()
	_ = s.Run(ctx, sequence.DeploymentRef{ID: "dep_X"})
	entries, _ := ledger.List(ctx, "dep_X")
	if len(entries) != 2 {
		t.Fatalf("want 2 entries; got %d", len(entries))
	}
	if entries[0].Status != sequence.LedgerStatusRolledBack {
		t.Errorf("a should be rolled_back; got %s", entries[0].Status)
	}
	if entries[1].Status != sequence.LedgerStatusFailed {
		t.Errorf("b should be failed; got %s", entries[1].Status)
	}
	if entries[1].ErrorMessage == "" {
		t.Errorf("b's error message should be recorded")
	}
}

func TestFromDeployment_CopiesFields(t *testing.T) {
	d := &deployments.Deployment{
		ID:              "dep_X",
		ProjectSlug:     "acme",
		EnvironmentSlug: "prod",
		ImageVersion:    "v0.3.1",
		PrimaryVhost:    "prod.acme.saas.omarss.net",
		Namespace:       "saas-dep_X",
		DBName:          "saas_acme_prod",
		DBAppRole:       "saas_acme_prod_app",
	}
	ref := sequence.FromDeployment(d)
	if ref.ID != d.ID || ref.PrimaryDomain != d.PrimaryVhost {
		t.Errorf("fields not copied: %+v", ref)
	}
}

func equalSlice(a, b []string) bool {
	return slices.Equal(a, b)
}
