package sequence

import (
	"context"
	"time"

	"github.com/omarss/saas/internal/controlplane/deployments"
)

// LedgerStatus enumerates step states. Mirrors the
// `deployment_provision_step.status` CHECK constraint in
// migration 000002.
type LedgerStatus string

// Allowed step statuses.
const (
	LedgerStatusPending    LedgerStatus = "pending"
	LedgerStatusRunning    LedgerStatus = "running"
	LedgerStatusCompleted  LedgerStatus = "completed"
	LedgerStatusFailed     LedgerStatus = "failed"
	LedgerStatusRolledBack LedgerStatus = "rolled_back"
)

// LedgerEntry is one row in the provision_step table. Kept narrow on
// purpose — the orchestrator and the destroy reconciler are the only
// readers.
type LedgerEntry struct {
	DeploymentID string
	StepName     string
	Status       LedgerStatus
	StartedAt    *time.Time
	CompletedAt  *time.Time
	ErrorMessage string
}

// Ledger persists per-step provisioning status. The pgx implementation
// lives in `internal/controlplane/deployments/ledger_pgx.go` (deferred —
// MVP runs an in-memory ledger so the destroy reconciler test matrix
// can exercise the orchestrator without spinning up Postgres). The
// Sequence consumes Ledger through this interface so a test ledger is
// cheap to substitute.
type Ledger interface {
	// Start moves a (deployment_id, step_name) row to status='running'
	// with started_at=now(). Creates the row if it does not exist.
	// Idempotent: re-calling Start on a row already 'completed' is a
	// no-op (returns nil) so retry-on-error flows do not need to
	// special-case the case "the step we just failed has already
	// finished on a parallel reconciler tick".
	Start(ctx context.Context, deploymentID, stepName string) error

	// Done moves the row to status='completed' with completed_at=now().
	Done(ctx context.Context, deploymentID, stepName string) error

	// Fail moves the row to status='failed' and records the error
	// message. The orchestrator calls this before the rollback chain.
	Fail(ctx context.Context, deploymentID, stepName string, err error) error

	// RolledBack marks a previously-completed step as having been
	// rolled back successfully. Used by the destroy reconciler.
	RolledBack(ctx context.Context, deploymentID, stepName string) error

	// ListCompletedReverse returns every row with status='completed'
	// for the given deployment_id, ORDERED LATEST FIRST. The
	// orchestrator (and the destroy reconciler) walk this list to run
	// Rollback callbacks in reverse-completion order.
	ListCompletedReverse(ctx context.Context, deploymentID string) ([]LedgerEntry, error)

	// List returns every row for a deployment in step-completion order
	// (earliest first). Used by `saasctl deployment ledger` for
	// operator forensics.
	List(ctx context.Context, deploymentID string) ([]LedgerEntry, error)
}

// MemoryLedger is the in-memory Ledger used by tests + the MVP wiring.
// It is safe for concurrent use because the destroy reconciler may run
// in parallel with an in-flight Provision; the lock is held only across
// map mutations so contention is negligible at the platform's scale.
type MemoryLedger struct {
	entries map[string][]LedgerEntry
}

// NewMemoryLedger returns a fresh in-memory ledger.
func NewMemoryLedger() *MemoryLedger {
	return &MemoryLedger{entries: map[string][]LedgerEntry{}}
}

// Start implements Ledger.
func (m *MemoryLedger) Start(_ context.Context, deploymentID, stepName string) error {
	now := time.Now().UTC()
	rows := m.entries[deploymentID]
	for i := range rows {
		if rows[i].StepName == stepName {
			if rows[i].Status == LedgerStatusCompleted {
				// Idempotent: already done.
				return nil
			}
			rows[i].Status = LedgerStatusRunning
			rows[i].StartedAt = &now
			rows[i].ErrorMessage = ""
			m.entries[deploymentID] = rows
			return nil
		}
	}
	m.entries[deploymentID] = append(rows, LedgerEntry{
		DeploymentID: deploymentID,
		StepName:     stepName,
		Status:       LedgerStatusRunning,
		StartedAt:    &now,
	})
	return nil
}

// Done implements Ledger.
func (m *MemoryLedger) Done(_ context.Context, deploymentID, stepName string) error {
	now := time.Now().UTC()
	rows := m.entries[deploymentID]
	for i := range rows {
		if rows[i].StepName == stepName {
			rows[i].Status = LedgerStatusCompleted
			rows[i].CompletedAt = &now
			m.entries[deploymentID] = rows
			return nil
		}
	}
	return nil
}

// Fail implements Ledger.
func (m *MemoryLedger) Fail(_ context.Context, deploymentID, stepName string, runErr error) error {
	rows := m.entries[deploymentID]
	for i := range rows {
		if rows[i].StepName == stepName {
			rows[i].Status = LedgerStatusFailed
			if runErr != nil {
				rows[i].ErrorMessage = runErr.Error()
			}
			m.entries[deploymentID] = rows
			return nil
		}
	}
	return nil
}

// RolledBack implements Ledger.
func (m *MemoryLedger) RolledBack(_ context.Context, deploymentID, stepName string) error {
	rows := m.entries[deploymentID]
	for i := range rows {
		if rows[i].StepName == stepName {
			rows[i].Status = LedgerStatusRolledBack
			m.entries[deploymentID] = rows
			return nil
		}
	}
	return nil
}

// ListCompletedReverse implements Ledger.
func (m *MemoryLedger) ListCompletedReverse(_ context.Context, deploymentID string) ([]LedgerEntry, error) {
	rows := m.entries[deploymentID]
	out := make([]LedgerEntry, 0, len(rows))
	for i := len(rows) - 1; i >= 0; i-- {
		if rows[i].Status == LedgerStatusCompleted {
			out = append(out, rows[i])
		}
	}
	return out, nil
}

// List implements Ledger.
func (m *MemoryLedger) List(_ context.Context, deploymentID string) ([]LedgerEntry, error) {
	rows := m.entries[deploymentID]
	out := make([]LedgerEntry, len(rows))
	copy(out, rows)
	return out, nil
}

// Compile-time assertion that MemoryLedger satisfies Ledger.
var _ Ledger = (*MemoryLedger)(nil)

// DeploymentRef is the data each step needs from a Deployment row. The
// orchestrator passes this value (not a pointer to deployments.Deployment)
// so a step cannot accidentally mutate the source. Constructed from a
// deployments.Deployment via FromDeployment.
type DeploymentRef struct {
	ID              string
	ProjectSlug     string
	EnvironmentSlug string
	ImageVersion    string
	PrimaryDomain   string
	CustomDomains   []string
	Namespace       string
	DBName          string
	RoleName        string
	NodePort        int
}

// FromDeployment derives a DeploymentRef from a deployments.Deployment.
// Field copy is explicit; callers should never reach into the source
// Deployment through this value.
func FromDeployment(d *deployments.Deployment) DeploymentRef {
	if d == nil {
		return DeploymentRef{}
	}
	return DeploymentRef{
		ID:              d.ID,
		ProjectSlug:     d.ProjectSlug,
		EnvironmentSlug: d.EnvironmentSlug,
		ImageVersion:    d.ImageVersion,
		PrimaryDomain:   d.PrimaryVhost,
		Namespace:       d.Namespace,
		DBName:          d.DBName,
		RoleName:        d.DBAppRole,
	}
}
