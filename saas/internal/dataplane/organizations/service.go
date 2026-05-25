package organizations

import (
	"context"
	"errors"
	"regexp"
	"strings"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/id"
)

// slugPattern mirrors the OpenAPI Organization.slug schema. Re-validated
// server-side as defence in depth — never trust the spec validator alone.
var slugPattern = regexp.MustCompile(`^[a-z][a-z0-9-]*[a-z0-9]$`)

// Input bounds mirror the OpenAPI schema. Repeated here so the service
// rejects bad input even when the request-validator middleware is
// bypassed in tests.
const (
	slugMinLen          = 2
	slugMaxLen          = 32
	nameMinLen          = 1
	nameMaxLen          = 120
	metadataMaxKeys     = 16
	metadataValueMaxLen = 256

	// DefaultOrganizationSlug is the slug used for the auto-created
	// organization that ships with every tenant. Per AGENTS.md §7, MVP
	// tenants have exactly one Organization unless multi_org is flipped.
	DefaultOrganizationSlug = "default"
	// DefaultOrganizationName is the human-readable default.
	DefaultOrganizationName = "Default Organization"

	// DefaultInvitationTTL is the default expires_at offset for new
	// invitations. Operators can override via the create-invitation
	// request body's expires_in_seconds field.
	DefaultInvitationTTL = 7 * 24 * time.Hour
	// MinInvitationTTL is the floor on caller-supplied TTLs.
	MinInvitationTTL = 1 * time.Hour
	// MaxInvitationTTL is the ceiling on caller-supplied TTLs.
	MaxInvitationTTL = 30 * 24 * time.Hour
)

// Service is the organizations application service. It validates input,
// orchestrates repository + notifier + outbox calls, and emits the ten
// audit events listed in the Phase 7 plan §7.8.
type Service struct {
	orgs          OrganizationRepo
	members       MemberRepo
	invites       InvitationRepo
	hasher        EmailHasher
	notifier      EmailNotifier
	tenants       TenantLookup
	users         UserLookup
	events        EventPublisher
	deploymentID  string
	publicBaseURL string
	now           func() time.Time
}

// Config groups Service constructor parameters.
type Config struct {
	OrganizationRepo OrganizationRepo
	MemberRepo       MemberRepo
	InvitationRepo   InvitationRepo
	EmailHasher      EmailHasher
	Notifier         EmailNotifier
	Tenants          TenantLookup
	Users            UserLookup
	Events           EventPublisher
	DeploymentID     string
	// PublicBaseURL is the per-Deployment data-plane vhost (e.g.
	// "https://dev.example.saas.omarss.net"). Invite URLs are built as
	// "<PublicBaseURL>/invitations/accept?token=<encodedToken>".
	PublicBaseURL string
}

// NewService constructs a Service from cfg.
func NewService(cfg Config) *Service {
	return &Service{
		orgs:          cfg.OrganizationRepo,
		members:       cfg.MemberRepo,
		invites:       cfg.InvitationRepo,
		hasher:        cfg.EmailHasher,
		notifier:      cfg.Notifier,
		tenants:       cfg.Tenants,
		users:         cfg.Users,
		events:        cfg.Events,
		deploymentID:  cfg.DeploymentID,
		publicBaseURL: cfg.PublicBaseURL,
		now:           time.Now,
	}
}

// WithClock substitutes the clock. Tests only.
func (s *Service) WithClock(now func() time.Time) *Service {
	s.now = now
	return s
}

// ---------------------------------------------------------------------------
// Organizations
// ---------------------------------------------------------------------------

// CreateOrganization persists a new organization in the caller's tenant.
// Returns ErrMultiOrgDisabled when the tenant has not opted in to
// multi-org. The default organization is created by AutoCreateDefault
// (called from the tenant.created subscriber); end-user-facing creates
// require multi_org=true.
func (s *Service) CreateOrganization(ctx context.Context, tenantID string, in CreateOrganizationInput) (Organization, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Organization{}, err
	}
	if err := validateSlug(in.Slug); err != nil {
		return Organization{}, err
	}
	if err := validateName(in.Name); err != nil {
		return Organization{}, err
	}
	if err := validateMetadata(in.Metadata); err != nil {
		return Organization{}, err
	}
	// Multi-org gate. The default organization is created via
	// AutoCreateDefault which bypasses this check intentionally.
	if s.tenants != nil {
		t, err := s.tenants.GetTenantBasic(ctx, tenantID)
		if err != nil {
			return Organization{}, err
		}
		if !t.MultiOrg {
			return Organization{}, ErrMultiOrgDisabled
		}
	}
	return s.persistOrganization(ctx, tenantID, in.Slug, in.Name, in.Metadata)
}

// AutoCreateDefault creates the default organization for a tenant. Used by
// the tenant.created subscriber and by the back-fill path; bypasses the
// multi_org check intentionally because every tenant gets a default
// organization regardless of the flag.
func (s *Service) AutoCreateDefault(ctx context.Context, tenantID string) (Organization, error) {
	// Idempotent — if a default org already exists return it.
	if existing, err := s.orgs.GetBySlug(ctx, tenantID, DefaultOrganizationSlug); err == nil {
		return existing, nil
	} else if !errors.Is(err, ErrNotFound) {
		return Organization{}, err
	}
	return s.persistOrganization(ctx, tenantID, DefaultOrganizationSlug, DefaultOrganizationName, nil)
}

func (s *Service) persistOrganization(ctx context.Context, tenantID, slug, name string, metadata map[string]string) (Organization, error) {
	now := s.now().UTC()
	o := Organization{
		ID:        id.New(id.PrefixOrg),
		TenantID:  tenantID,
		Slug:      slug,
		Name:      name,
		Status:    OrganizationStatusActive,
		Metadata:  metadata,
		RowSeq:    1,
		CreatedAt: now,
		UpdatedAt: now,
	}
	created, err := s.orgs.Create(ctx, o)
	if err != nil {
		return Organization{}, err
	}
	_ = s.events.Publish(ctx, "organization.created", created.TenantID, map[string]any{
		"organization_id": created.ID,
		"tenant_id":       created.TenantID,
		"slug":            created.Slug,
		"name":            created.Name,
	})
	return created, nil
}

// CreateOrganizationInput is the application-level input to
// CreateOrganization. The handler builds it from the OpenAPI request.
type CreateOrganizationInput struct {
	Slug     string
	Name     string
	Metadata map[string]string
}

// GetOrganization returns an organization scoped to the caller's tenant.
func (s *Service) GetOrganization(ctx context.Context, tenantID, organizationID string) (Organization, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Organization{}, err
	}
	return s.orgs.Get(ctx, tenantID, organizationID)
}

// ListOrganizations enumerates organizations in the caller's tenant.
func (s *Service) ListOrganizations(ctx context.Context, tenantID string, limit int, cursor *OrgListCursor) ([]Organization, bool, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return nil, false, err
	}
	if limit <= 0 || limit > 200 {
		limit = 25
	}
	return s.orgs.List(ctx, tenantID, limit, cursor)
}

// UpdateOrganization applies a patch under optimistic concurrency.
func (s *Service) UpdateOrganization(ctx context.Context, tenantID, organizationID string, expectedSeq int64, patch OrgPatch) (Organization, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Organization{}, err
	}
	if patch.Name != nil {
		if err := validateName(*patch.Name); err != nil {
			return Organization{}, err
		}
	}
	if patch.Status != nil {
		switch *patch.Status {
		case OrganizationStatusActive, OrganizationStatusSuspended:
			// allowed via PATCH; "deleted" is reachable only through DELETE
		default:
			return Organization{}, ErrInvalidInput
		}
	}
	if patch.PatchMetadata {
		if err := validateMetadata(patch.Metadata); err != nil {
			return Organization{}, err
		}
	}
	updated, err := s.orgs.Update(ctx, tenantID, organizationID, expectedSeq, patch)
	if err != nil {
		return Organization{}, err
	}
	_ = s.events.Publish(ctx, "organization.updated", updated.TenantID, map[string]any{
		"organization_id": updated.ID,
	})
	return updated, nil
}

// DeleteOrganization soft-deletes an organization. Refuses if any
// active members remain — the operator must remove members first
// (a future tenant.purge path may bypass this for full deletion).
func (s *Service) DeleteOrganization(ctx context.Context, tenantID, organizationID string, expectedSeq int64) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	active, err := s.members.CountActive(ctx, organizationID)
	if err != nil {
		return err
	}
	if active > 0 {
		return ErrInvalidInput
	}
	deleted, err := s.orgs.SoftDelete(ctx, tenantID, organizationID, expectedSeq)
	if err != nil {
		return err
	}
	_ = s.events.Publish(ctx, "organization.deleted", deleted.TenantID, map[string]any{
		"organization_id": deleted.ID,
	})
	return nil
}

// ---------------------------------------------------------------------------
// Members
// ---------------------------------------------------------------------------

// GetMember returns a member scoped to the caller's tenant.
func (s *Service) GetMember(ctx context.Context, tenantID, memberID string) (Member, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Member{}, err
	}
	return s.members.Get(ctx, tenantID, memberID)
}

// ListMembers enumerates members in an organization. Phase 7 allows any
// tenant member to list members of any organization in their tenant;
// Phase 8 RBAC may tighten this with a per-org permission.
func (s *Service) ListMembers(ctx context.Context, tenantID, organizationID string, limit int, cursor *MemberListCursor) ([]Member, bool, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return nil, false, err
	}
	// Confirm the organization belongs to the caller's tenant. Returns
	// ErrNotFound (not 403) to avoid existence leaks.
	if _, err := s.orgs.Get(ctx, tenantID, organizationID); err != nil {
		return nil, false, err
	}
	if limit <= 0 || limit > 200 {
		limit = 25
	}
	return s.members.List(ctx, tenantID, organizationID, limit, cursor)
}

// UpdateMemberRole reassigns a member's role. Phase 7 ships the column
// (text placeholder, no FK); Phase 8 RBAC adds validation against the
// role table.
func (s *Service) UpdateMemberRole(ctx context.Context, tenantID, memberID string, expectedSeq int64, roleID *string) (Member, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Member{}, err
	}
	updated, err := s.members.UpdateRole(ctx, tenantID, memberID, expectedSeq, roleID)
	if err != nil {
		return Member{}, err
	}
	_ = s.events.Publish(ctx, "member.role_changed", updated.TenantID, map[string]any{
		"member_id":       updated.ID,
		"organization_id": updated.OrganizationID,
		"user_id":         updated.UserID,
		"role_id":         updated.RoleID,
	})
	return updated, nil
}

// RemoveMember soft-removes a member (status='removed').
func (s *Service) RemoveMember(ctx context.Context, tenantID, memberID string, expectedSeq int64) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	removed, err := s.members.Remove(ctx, tenantID, memberID, expectedSeq)
	if err != nil {
		return err
	}
	_ = s.events.Publish(ctx, "member.removed", removed.TenantID, map[string]any{
		"member_id":       removed.ID,
		"organization_id": removed.OrganizationID,
		"user_id":         removed.UserID,
	})
	return nil
}

// ---------------------------------------------------------------------------
// validation
// ---------------------------------------------------------------------------

func validateSlug(slug string) error {
	if len(slug) < slugMinLen || len(slug) > slugMaxLen || !slugPattern.MatchString(slug) {
		return ErrInvalidInput
	}
	return nil
}

func validateName(name string) error {
	name = strings.TrimSpace(name)
	if len(name) < nameMinLen || len(name) > nameMaxLen {
		return ErrInvalidInput
	}
	return nil
}

func validateMetadata(m map[string]string) error {
	if len(m) > metadataMaxKeys {
		return ErrInvalidInput
	}
	for _, v := range m {
		if len(v) > metadataValueMaxLen {
			return ErrInvalidInput
		}
	}
	return nil
}
