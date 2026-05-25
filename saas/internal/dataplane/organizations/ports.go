package organizations

import (
	"context"
	"time"
)

// OrganizationRepo abstracts persistence for the Organization aggregate.
// The pgx implementation lives in repo_pgx.go; service unit tests pass an
// in-memory fake.
type OrganizationRepo interface {
	Create(ctx context.Context, o Organization) (Organization, error)
	Get(ctx context.Context, tenantID, orgID string) (Organization, error)
	GetBySlug(ctx context.Context, tenantID, slug string) (Organization, error)
	List(ctx context.Context, tenantID string, limit int, cursor *OrgListCursor) ([]Organization, bool, error)
	Update(ctx context.Context, tenantID, orgID string, expectedSeq int64, patch OrgPatch) (Organization, error)
	SoftDelete(ctx context.Context, tenantID, orgID string, expectedSeq int64) (Organization, error)
}

// MemberRepo abstracts persistence for the Member aggregate.
type MemberRepo interface {
	Create(ctx context.Context, m Member) (Member, error)
	Get(ctx context.Context, tenantID, memberID string) (Member, error)
	GetByUser(ctx context.Context, organizationID, userID string) (Member, error)
	List(ctx context.Context, tenantID, organizationID string, limit int, cursor *MemberListCursor) ([]Member, bool, error)
	UpdateRole(ctx context.Context, tenantID, memberID string, expectedSeq int64, roleID *string) (Member, error)
	Remove(ctx context.Context, tenantID, memberID string, expectedSeq int64) (Member, error)
	CountActive(ctx context.Context, organizationID string) (int64, error)
}

// InvitationRepo abstracts persistence for the Invitation aggregate.
// Cross-tenant lookups by token hash are intentionally permitted at the
// repo layer — the accept flow does not know the tenant until the row is
// resolved (see invite.go for the exception documentation).
type InvitationRepo interface {
	Create(ctx context.Context, inv Invitation) (Invitation, error)
	Get(ctx context.Context, tenantID, invitationID string) (Invitation, error)
	GetByTokenHash(ctx context.Context, tokenHash []byte) (Invitation, error)
	GetPendingByEmailHash(ctx context.Context, organizationID string, emailHash []byte) (Invitation, error)
	List(ctx context.Context, tenantID, organizationID string, limit int) ([]Invitation, error)
	MarkAccepted(ctx context.Context, invitationID, acceptedByUserID string) (Invitation, error)
	MarkRevoked(ctx context.Context, tenantID, invitationID string, expectedSeq int64, revokedByUserID string) (Invitation, error)
	ExpireOverdue(ctx context.Context, now time.Time) ([]ExpiredRow, error)
}

// ExpiredRow is returned by the sweeper so the caller can emit one
// outbox event per flipped invitation without re-reading the row.
type ExpiredRow struct {
	InvitationID   string
	TenantID       string
	OrganizationID string
}

// EmailHasher hashes invitee email addresses with the per-Deployment
// HMAC key. Identity's hasher implements this interface; sharing the
// hasher means an invited email can be re-linked to the resulting User
// row deterministically without storing plaintext on either side.
type EmailHasher interface {
	Normalise(email string) string
	Hash(ctx context.Context, deploymentID, email string) ([]byte, error)
}

// EmailNotifier is the narrow Notifications port. The notifications
// service is the production implementation; tests pass a stub that
// records the invite URL + recipient for assertion.
//
// The interface is wider than necessary so the service does not need to
// know about workflow names or payload schemas — it simply hands off
// the rendered URL + display strings.
type EmailNotifier interface {
	// SendInvitation dispatches the platform "member.invited" workflow.
	// Returns nil on successful enqueue (Phase 6 ships queued+id;
	// terminal delivery state is owned by the worker).
	//
	// Implementations MUST NOT log the invitee email — the
	// notifications module already redacts payload contents.
	SendInvitation(ctx context.Context, in SendInvitationInput) error
}

// SendInvitationInput gathers the fields the invite email template
// needs. Centralised so the service signature stays stable when the
// notification template gains fields.
type SendInvitationInput struct {
	TenantID         string
	InviteeUserID    string // optional — empty when the invitee has no User yet
	InviteeEmail     string
	OrganizationID   string
	OrganizationName string
	InviterUserID    string
	InviterName      string
	AcceptURL        string
	ExpiresAt        time.Time
}

// EventPublisher is the outbox port. Mirrors the Identity / Tenancy /
// Notifications modules.
type EventPublisher interface {
	Publish(ctx context.Context, eventType, tenantID string, payload map[string]any) error
}

// TenantLookup is the narrow read-side port the service uses to resolve
// the multi_org flag + display name from the Tenant row. The tenancy
// service implements it. The dependency intentionally avoids importing
// the tenancy package (no circular deps in case Phase 8 RBAC layers on
// both modules).
type TenantLookup interface {
	GetTenantBasic(ctx context.Context, tenantID string) (TenantBasic, error)
}

// TenantBasic is the narrow tenant view consumed by this module.
type TenantBasic struct {
	ID                    string
	Name                  string
	Slug                  string
	DefaultOrganizationID *string
	MultiOrg              bool
}

// UserLookup resolves the calling user's email + display name during
// the accept flow so the service can constant-time-compare to the
// invitee email. Identity's repository implements it.
type UserLookup interface {
	LookupUser(ctx context.Context, tenantID, userID string) (UserInfo, error)
}

// UserInfo is the narrow user view consumed by this module. The
// decrypted email is treated as PII and is zeroed by the caller after
// the comparison.
type UserInfo struct {
	UserID string
	Email  string
	Name   string
}
