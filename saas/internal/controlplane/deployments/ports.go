package deployments

import (
	"context"
	"time"
)

// Repository abstracts persistence of Deployment rows. Tests substitute
// an in-memory fake; the pgx impl lives in repo_pgx.go.
type Repository interface {
	Create(ctx context.Context, d Deployment) (Deployment, error)
	Get(ctx context.Context, id string) (Deployment, error)
	GetBySlug(ctx context.Context, projectSlug, environmentSlug string) (Deployment, error)
	List(ctx context.Context, filter ListFilter) ([]Deployment, bool, error)
	UpdateStatus(ctx context.Context, id string, status Status) error
	UpdateImage(ctx context.Context, id string, expectedSeq int64, newImage string) (Deployment, error)
	UpdateRetention(ctx context.Context, id string, until *time.Time) error
}

// ListFilter is the decoded form of /control/v1/deployments query params.
type ListFilter struct {
	Limit  int
	Status string
	Cursor *ListCursor
}

// ListCursor is the keyset pagination cursor for Deployment.List.
type ListCursor struct {
	CreatedAt time.Time
	ID        string
}

// DomainRepository abstracts BYOD attachment persistence.
type DomainRepository interface {
	Create(ctx context.Context, dd DeploymentDomain) (DeploymentDomain, error)
	Get(ctx context.Context, deploymentID, domainID string) (DeploymentDomain, error)
	List(ctx context.Context, deploymentID string) ([]DeploymentDomain, error)
	CountActive(ctx context.Context, deploymentID string) (int, error)
	UpdateCheck(ctx context.Context, id string, status DomainStatus, at time.Time, lastErr string) (DeploymentDomain, error)
	MarkRemoved(ctx context.Context, id string) error
}

// RevisionRepository tracks per-Deployment image_version history.
type RevisionRepository interface {
	Create(ctx context.Context, r Revision) (Revision, error)
	List(ctx context.Context, deploymentID string) ([]Revision, error)
	Latest(ctx context.Context, deploymentID string) (Revision, error)
}

// EventPublisher is the control-plane outbox port. Phase 11 wires the
// logger publisher; real downstream consumers (control-plane audit
// subscriber, k8s reconciler) attach in Phase 12.
type EventPublisher interface {
	Publish(ctx context.Context, eventType, deploymentID string, payload map[string]any) error
}

// DNSResolver wraps net.LookupTXT so domain verification is testable.
// The default impl uses net.DefaultResolver; tests inject a fake that
// returns pre-seeded TXT records.
type DNSResolver interface {
	LookupTXT(ctx context.Context, name string) ([]string, error)
}

// Provisioner is the seam between the control plane and the host. Phase 11
// ships LocalProvisioner (Postgres-only). Phase 12a-e add adapters that
// touch nginx, k3s, OpenBao, and certbot.
//
// Every method is idempotent — re-running on a partially-completed
// deployment is safe. Failures leave the deployment_provision_step rows
// in `failed` state for the destroy reconciler to retry or roll back.
type Provisioner interface {
	Provision(ctx context.Context, d *Deployment) (BootstrapResult, error)
	Upgrade(ctx context.Context, d *Deployment, newImage string, runMigrations bool) error
	Rollback(ctx context.Context, d *Deployment, previousImage string) error
	Restart(ctx context.Context, d *Deployment) error
	Restore(ctx context.Context, oldDep *Deployment, toTimestamp time.Time) (*Deployment, error)
	Destroy(ctx context.Context, d *Deployment) error
	Purge(ctx context.Context, d *Deployment) error

	AttachDomain(ctx context.Context, d *Deployment, dd *DeploymentDomain) error
	VerifyDomain(ctx context.Context, d *Deployment, dd *DeploymentDomain) (bool, error)
	DetachDomain(ctx context.Context, d *Deployment, dd *DeploymentDomain) error
}
