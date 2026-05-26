package sequence

import (
	"context"
	"fmt"
	"time"

	"github.com/omarss/saas/internal/controlplane/deployments"
)

// HostShim adapts a Sequence + Adapters bundle to the
// deployments.HostProvisionerSeq interface used by HostProvisioner.
//
// The shim exists because Sequence.Run takes a DeploymentRef while
// the HostProvisionerSeq.Run takes a *deployments.Deployment; this
// glue file converts between the two without dragging the sequence
// package into a hard dependency on the deployments package's mutable
// pointer surface.
type HostShim struct {
	Seq       *Sequence
	Adapters  Adapters
	Bootstrap BootstrapStore

	// FlipStatusToDestroying is used by HostProvisioner.Destroy — it
	// flips the deployment row to status='destroying' so the reconciler
	// picks it up on the next tick. The shim does not run the destroy
	// inline; the reconciler is the single source of truth for
	// tear-down (matches the AGENTS.md §6.4 model).
	Status StatusUpdater
}

// NewHostShim builds the shim. seq + adapters required.
func NewHostShim(seq *Sequence, adapters Adapters, bootstrap BootstrapStore, status StatusUpdater) *HostShim {
	if bootstrap == nil {
		bootstrap = NewMemoryBootstrapStore()
	}
	return &HostShim{
		Seq:       seq,
		Adapters:  adapters,
		Bootstrap: bootstrap,
		Status:    status,
	}
}

// Run wraps Sequence.Run.
func (s *HostShim) Run(ctx context.Context, d *deployments.Deployment) error {
	return s.Seq.Run(ctx, FromDeployment(d))
}

// Upgrade wraps Sequence.Upgrade.
func (s *HostShim) Upgrade(ctx context.Context, d *deployments.Deployment, newImage string, runMigrations bool) error {
	return s.Seq.Upgrade(ctx, d, s.Adapters, UpgradeOptions{
		NewImageVersion: newImage,
		RunMigrations:   runMigrations,
	})
}

// Rollback wraps Sequence.Rollback.
func (s *HostShim) Rollback(ctx context.Context, d *deployments.Deployment, previousImage string) error {
	return s.Seq.Rollback(ctx, d, s.Adapters, previousImage)
}

// Restart wraps Sequence.Restart.
func (s *HostShim) Restart(ctx context.Context, d *deployments.Deployment) error {
	return s.Seq.Restart(ctx, d, s.Adapters)
}

// Restore wraps Sequence.Restore.
func (s *HostShim) Restore(ctx context.Context, oldDep *deployments.Deployment, toTimestamp time.Time) (*deployments.Deployment, error) {
	return s.Seq.Restore(ctx, oldDep, s.Adapters, toTimestamp)
}

// Destroy flips the deployment to status='destroying'. The destroy
// reconciler picks it up on the next tick.
func (s *HostShim) Destroy(ctx context.Context, d *deployments.Deployment) error {
	if s.Status == nil {
		return fmt.Errorf("%w: status updater required", ErrAdapterNil)
	}
	return s.Status.UpdateStatus(ctx, d.ID, deployments.StatusDestroying)
}

// Purge wraps Sequence.Purge.
func (s *HostShim) Purge(ctx context.Context, d *deployments.Deployment) error {
	return s.Seq.Purge(ctx, d, s.Adapters)
}

// FreezeKeys wraps Sequence.FreezeKeys.
func (s *HostShim) FreezeKeys(ctx context.Context, d *deployments.Deployment, reason string) error {
	return s.Seq.FreezeKeys(ctx, d, s.Adapters, reason)
}

// BootstrapFor returns + deletes the one-time bootstrap result.
func (s *HostShim) BootstrapFor(deploymentID string) (deployments.BootstrapResult, bool) {
	b, ok := s.Bootstrap.Get(deploymentID)
	if ok {
		s.Bootstrap.Delete(deploymentID)
	}
	return b, ok
}

// Compile-time assertion that HostShim satisfies the interface.
var _ deployments.HostProvisionerSeq = (*HostShim)(nil)
