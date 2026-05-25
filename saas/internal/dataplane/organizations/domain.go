// Package organizations is the Phase 7 vertical slice: organizations +
// members + invitations. Hexagonal layout mirrors Phase 5 identity /
// Phase 6 notifications (CONVENTIONS.md §1):
//
//	handler.go        HTTP boundary (wired in a follow-up patch once
//	                  OpenAPI codegen lands the new operationIds)
//	service.go        application orchestration
//	ports.go          OrgRepo / MemberRepo / InvitationRepo +
//	                  EmailNotifier + EmailHasher + EventPublisher
//	repo_pgx.go       pgx-backed implementations
//	invite.go         invitation create / accept / revoke + sweeper
//	domain.go         Organization / Member / Invitation + envelope siblings
//	errors.go         sentinel errors translated to HTTP problems
//
// PII handling: Invitation declares InviteeEmailEnvelope as the sibling of
// the InviteeEmail field (CONVENTIONS.md §10.1). The repository invokes
// crypto.EncryptPIIFieldsStrict before every INSERT — strict mode refuses
// silent envelope drop. AAD is the new format
// deployment_id|resource_type|resource_id|field_name.
//
// Tokens: the accept-token is generated with crypto/rand (32 bytes),
// base64-url-encoded for the email, sha256-hashed for DB lookup, and the
// first 8 chars of the encoding are kept as token_prefix for operator
// readability. Plaintext tokens NEVER touch the DB; constant-time
// (crypto/subtle) compare protects against timing oracles at accept time.
package organizations

import (
	"time"

	"github.com/omarss/saas/internal/platform/crypto"
	"github.com/omarss/saas/internal/platform/etag"
)

// OrganizationStatus enumerates Organization lifecycle states. "deleted"
// is the soft-delete terminal state; "suspended" is reserved for future
// admin-driven freezes.
type OrganizationStatus string

// Allowed organization statuses.
const (
	OrganizationStatusActive    OrganizationStatus = "active"
	OrganizationStatusSuspended OrganizationStatus = "suspended"
	OrganizationStatusDeleted   OrganizationStatus = "deleted"
)

// Valid reports whether s is one of the platform's allowed states.
func (s OrganizationStatus) Valid() bool {
	switch s {
	case OrganizationStatusActive, OrganizationStatusSuspended, OrganizationStatusDeleted:
		return true
	}
	return false
}

// MemberStatus enumerates Member lifecycle states. "removed" is the
// soft-delete terminal state — the row is retained for audit chain
// continuity.
type MemberStatus string

// Allowed member statuses.
const (
	MemberStatusActive    MemberStatus = "active"
	MemberStatusSuspended MemberStatus = "suspended"
	MemberStatusRemoved   MemberStatus = "removed"
)

// Valid reports whether s is one of the platform's allowed states.
func (s MemberStatus) Valid() bool {
	switch s {
	case MemberStatusActive, MemberStatusSuspended, MemberStatusRemoved:
		return true
	}
	return false
}

// InvitationStatus enumerates Invitation lifecycle states.
type InvitationStatus string

// Allowed invitation statuses.
const (
	InvitationStatusPending  InvitationStatus = "pending"
	InvitationStatusAccepted InvitationStatus = "accepted"
	InvitationStatusRevoked  InvitationStatus = "revoked"
	InvitationStatusExpired  InvitationStatus = "expired"
)

// Valid reports whether s is one of the platform's allowed states.
func (s InvitationStatus) Valid() bool {
	switch s {
	case InvitationStatusPending, InvitationStatusAccepted,
		InvitationStatusRevoked, InvitationStatusExpired:
		return true
	}
	return false
}

// Organization is the in-memory representation passed between handler,
// service, repository, and outbox. AGENTS.md §7: Organization sits
// inside a Tenant; tenant remains the isolation + billing boundary.
type Organization struct {
	ID        string
	TenantID  string
	Slug      string
	Name      string
	Status    OrganizationStatus
	Metadata  map[string]string
	RowSeq    int64
	CreatedAt time.Time
	UpdatedAt time.Time
	DeletedAt *time.Time
}

// ETag returns the platform's Weak ETag for this organization.
func (o Organization) ETag() string { return etag.Format(o.RowSeq) }

// OrgPatch carries optional PATCH fields for /v1/organizations/{id}.
// nil means "do not change this column".
type OrgPatch struct {
	Name          *string
	Status        *OrganizationStatus
	Metadata      map[string]string
	PatchMetadata bool
}

// Member is the in-memory representation of a User's membership in an
// Organization. role_id is a Phase 8 RBAC forward placeholder.
type Member struct {
	ID             string
	TenantID       string
	OrganizationID string
	UserID         string
	RoleID         *string
	Status         MemberStatus
	Metadata       map[string]string
	RowSeq         int64
	JoinedAt       time.Time
	UpdatedAt      time.Time
	RemovedAt      *time.Time
}

// ETag returns the platform's Weak ETag for this member.
func (m Member) ETag() string { return etag.Format(m.RowSeq) }

// Invitation is the in-memory representation of a pending / consumed
// invite. The plaintext InviteeEmail field is populated only on the read
// path (after the persistence-layer decrypt) and on the write path it
// is cleared by the strict-mode walker immediately after wrapping into
// InviteeEmailEnvelope.
//
// TokenPrefix is the human-readable first 8 chars of the base64-url
// plaintext token. TokenHash is sha256(rawToken); both back the constant-
// time accept-token lookup. The raw token is NEVER stored — it travels
// only in the invitation email body.
type Invitation struct {
	ID                   string
	TenantID             string
	OrganizationID       string
	InviteeEmail         string `pii:"true" sensitive:"true"`
	InviteeEmailEnvelope crypto.Envelope
	InviteeEmailHash     []byte
	TokenHash            []byte
	TokenPrefix          string
	InvitedByUserID      string
	ProposedRoleID       *string
	Status               InvitationStatus
	ExpiresAt            time.Time
	AcceptedAt           *time.Time
	AcceptedByUserID     *string
	RevokedAt            *time.Time
	RevokedByUserID      *string
	RowSeq               int64
	CreatedAt            time.Time
	UpdatedAt            time.Time
}

// ETag returns the platform's Weak ETag for this invitation.
func (i Invitation) ETag() string { return etag.Format(i.RowSeq) }

// OrgListCursor is the decoded cursor for ListOrganizations.
type OrgListCursor struct {
	CreatedAt time.Time
	ID        string
}

// MemberListCursor is the decoded cursor for ListMembers.
type MemberListCursor struct {
	JoinedAt time.Time
	ID       string
}
