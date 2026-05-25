// Package deployments owns the control-plane Deployment resource model:
// CRUD, lifecycle (upgrade/rollback/restart/restore/purge), BYOD custom
// domains, and the local-mode provisioner.
//
// Phase 11 ships only the LocalProvisioner — Postgres DB creation +
// data-plane migrations + bootstrap tenant seed. The other host writes
// (nginx, k3s, OpenBao, certbot) land in Phase 12a-e behind the
// Provisioner interface declared here.
//
// Hexagonal layout mirrors `internal/dataplane/tenancy/`:
//
//	domain.go            Deployment + DeploymentDomain + status enums
//	errors.go            sentinel errors mapped to HTTP problems
//	ports.go             Repository + DomainRepository + Provisioner
//	provisioner_local.go LocalProvisioner — Postgres-only Phase 11 impl
//	repo_pgx.go          pgx-backed repositories
//	service.go           lifecycle orchestration
//	domain_service.go    BYOD attach / verify / detach
//	handler.go           HTTP boundary (oapi-codegen StrictServerInterface)
package deployments

import (
	"time"
)

// Status enumerates the Deployment lifecycle states. Mirrors the
// migrations/controlplane/000002 CHECK constraint and the OpenAPI
// Deployment.status enum.
type Status string

// Allowed Deployment statuses.
const (
	StatusProvisioning Status = "provisioning"
	StatusActive       Status = "active"
	StatusSuspended    Status = "suspended"
	StatusUpgrading    Status = "upgrading"
	StatusFailed       Status = "failed"
	StatusDestroying   Status = "destroying"
	StatusDestroyed    Status = "destroyed"
	StatusRestoring    Status = "restoring"
	StatusPurging      Status = "purging"
	StatusPurged       Status = "purged"
)

// Valid reports whether s is a recognised status. Defensive check used by
// the repo when reading rows; the DB CHECK constraint is the primary guard.
func (s Status) Valid() bool {
	switch s {
	case StatusProvisioning, StatusActive, StatusSuspended, StatusUpgrading,
		StatusFailed, StatusDestroying, StatusDestroyed, StatusRestoring,
		StatusPurging, StatusPurged:
		return true
	}
	return false
}

// Deployment is the control-plane resource. Field naming follows
// AGENTS.md §12.1.
type Deployment struct {
	ID              string
	ProjectSlug     string
	EnvironmentSlug string
	Region          string
	Modules         []string
	ImageVersion    string
	DataResidency   string
	PrimaryVhost    string
	Status          Status
	DBName          string
	DBAppRole       string
	Namespace       string
	BaoKid          string
	Metadata        map[string]string
	LastEventID     string
	RetainUntil     *time.Time
	RowSeq          int64
	CreatedAt       time.Time
	UpdatedAt       time.Time
}

// DomainStatus mirrors the deployment_domain.status enum.
type DomainStatus string

// Allowed BYOD domain states. "removed" is a tombstone — the row is kept
// so audit can still trace the detach event.
const (
	DomainStatusPending  DomainStatus = "pending"
	DomainStatusVerified DomainStatus = "verified"
	DomainStatusFailed   DomainStatus = "failed"
	DomainStatusRemoved  DomainStatus = "removed"
)

// VerificationRecord is the DNS TXT challenge the operator publishes to
// prove ownership before certbot is invoked (Phase 12a).
// See ADR 015.
type VerificationRecord struct {
	RecordName  string // _saas-verify.<domain>
	RecordType  string // always "TXT"
	RecordValue string // saas-verify=<hex(HMAC-SHA256(...))>
}

// DeploymentDomain is a BYOD attachment.
type DeploymentDomain struct {
	ID                 string
	DeploymentID       string
	Domain             string
	IsPrimary          bool
	Status             DomainStatus
	VerificationMethod string
	VerificationRecord VerificationRecord
	VerificationToken  string
	VerifiedAt         *time.Time
	LastCheckAt        *time.Time
	LastCheckError     string
	CertStatus         string
	CertIssuedAt       *time.Time
	CreatedAt          time.Time
}

// Revision is a single image_version rollout entry. Used by /revisions
// and rollback.
type Revision struct {
	ID            string
	DeploymentID  string
	ImageVersion  string
	AppliedAt     time.Time
	IsRolledBack  bool
	AppliedBy     string
	Metadata      map[string]string
}

// BootstrapResult is what the LocalProvisioner returns to the handler so
// the create response can include the one-time first-tenant API key.
// The secret is never persisted on the control plane — the operator must
// capture it from the response.
type BootstrapResult struct {
	BootstrapTenantID     string
	BootstrapAPIKeyID     string
	BootstrapAPIKeySecret string
}
