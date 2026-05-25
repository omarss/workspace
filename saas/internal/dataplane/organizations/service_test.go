package organizations_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/omarss/saas/internal/dataplane/organizations"
	"github.com/omarss/saas/internal/platform/auth"
)

// packageReferencesConstantTime asserts the invite.go source uses the
// constant-time comparator. This is a guardrail against a future refactor
// regressing the timing-attack defence.
func packageReferencesConstantTime() bool {
	_, thisFile, _, _ := runtime.Caller(0)
	dir := filepath.Dir(thisFile)
	// gosec G304: path is derived from runtime.Caller (this very test
	// file's location) — there is no external input. Safe.
	data, err := os.ReadFile(filepath.Join(dir, "invite.go")) //nolint:gosec
	if err != nil {
		return false
	}
	src := string(data)
	return strings.Contains(src, `"crypto/subtle"`) && strings.Contains(src, "subtle.ConstantTimeCompare")
}

// ---------------------------------------------------------------------------
// In-memory fakes
//
// These mirror the notifications / identity test-double pattern: they do not
// emulate RLS (covered by repo_pgx_test integration) and they do not run the
// envelope walker (covered by encrypt_persist_test). The fakes exist so the
// service-level tests can assert business behaviour, validation, and event
// emission without spinning a Postgres container.
// ---------------------------------------------------------------------------

type fakeOrgRepo struct {
	mu     sync.Mutex
	orgs   map[string]organizations.Organization
	bySlug map[string]string // tenantID|slug -> orgID
}

func newFakeOrgRepo() *fakeOrgRepo {
	return &fakeOrgRepo{
		orgs:   map[string]organizations.Organization{},
		bySlug: map[string]string{},
	}
}

func slugKey(tenant, slug string) string { return tenant + "|" + slug }

func (r *fakeOrgRepo) Create(_ context.Context, o organizations.Organization) (organizations.Organization, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	k := slugKey(o.TenantID, o.Slug)
	if _, exists := r.bySlug[k]; exists {
		return organizations.Organization{}, organizations.ErrSlugTaken
	}
	r.orgs[o.ID] = o
	r.bySlug[k] = o.ID
	return o, nil
}

func (r *fakeOrgRepo) Get(_ context.Context, tenantID, orgID string) (organizations.Organization, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	o, ok := r.orgs[orgID]
	if !ok || o.TenantID != tenantID || o.DeletedAt != nil {
		return organizations.Organization{}, organizations.ErrNotFound
	}
	return o, nil
}

func (r *fakeOrgRepo) GetBySlug(_ context.Context, tenantID, slug string) (organizations.Organization, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	id, ok := r.bySlug[slugKey(tenantID, slug)]
	if !ok {
		return organizations.Organization{}, organizations.ErrNotFound
	}
	o := r.orgs[id]
	if o.DeletedAt != nil {
		return organizations.Organization{}, organizations.ErrNotFound
	}
	return o, nil
}

func (r *fakeOrgRepo) List(_ context.Context, tenantID string, _ int, _ *organizations.OrgListCursor) ([]organizations.Organization, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]organizations.Organization, 0)
	for _, o := range r.orgs {
		if o.TenantID == tenantID && o.DeletedAt == nil {
			out = append(out, o)
		}
	}
	return out, false, nil
}

func (r *fakeOrgRepo) Update(_ context.Context, tenantID, orgID string, expectedSeq int64, patch organizations.OrgPatch) (organizations.Organization, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	o, ok := r.orgs[orgID]
	if !ok || o.TenantID != tenantID {
		return organizations.Organization{}, organizations.ErrNotFound
	}
	if o.RowSeq != expectedSeq {
		return organizations.Organization{}, organizations.ErrETagMismatch
	}
	if patch.Name != nil {
		o.Name = *patch.Name
	}
	if patch.Status != nil {
		o.Status = *patch.Status
	}
	if patch.PatchMetadata {
		o.Metadata = patch.Metadata
	}
	o.RowSeq++
	r.orgs[orgID] = o
	return o, nil
}

func (r *fakeOrgRepo) SoftDelete(_ context.Context, tenantID, orgID string, expectedSeq int64) (organizations.Organization, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	o, ok := r.orgs[orgID]
	if !ok || o.TenantID != tenantID {
		return organizations.Organization{}, organizations.ErrNotFound
	}
	if o.RowSeq != expectedSeq {
		return organizations.Organization{}, organizations.ErrETagMismatch
	}
	now := time.Now()
	o.DeletedAt = &now
	o.Status = organizations.OrganizationStatusDeleted
	o.RowSeq++
	r.orgs[orgID] = o
	return o, nil
}

type fakeMemberRepo struct {
	mu      sync.Mutex
	members map[string]organizations.Member
}

func newFakeMemberRepo() *fakeMemberRepo {
	return &fakeMemberRepo{members: map[string]organizations.Member{}}
}

func (r *fakeMemberRepo) Create(_ context.Context, m organizations.Member) (organizations.Member, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	// Duplicate active membership check.
	for _, existing := range r.members {
		if existing.OrganizationID == m.OrganizationID &&
			existing.UserID == m.UserID &&
			existing.Status == organizations.MemberStatusActive {
			return organizations.Member{}, organizations.ErrMemberExists
		}
	}
	r.members[m.ID] = m
	return m, nil
}

func (r *fakeMemberRepo) Get(_ context.Context, tenantID, memberID string) (organizations.Member, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	m, ok := r.members[memberID]
	if !ok || m.TenantID != tenantID {
		return organizations.Member{}, organizations.ErrNotFound
	}
	return m, nil
}

func (r *fakeMemberRepo) GetByUser(_ context.Context, organizationID, userID string) (organizations.Member, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, m := range r.members {
		if m.OrganizationID == organizationID && m.UserID == userID && m.Status == organizations.MemberStatusActive {
			return m, nil
		}
	}
	return organizations.Member{}, organizations.ErrNotFound
}

func (r *fakeMemberRepo) List(_ context.Context, tenantID, orgID string, _ int, _ *organizations.MemberListCursor) ([]organizations.Member, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]organizations.Member, 0)
	for _, m := range r.members {
		if m.TenantID == tenantID && m.OrganizationID == orgID && m.Status != organizations.MemberStatusRemoved {
			out = append(out, m)
		}
	}
	return out, false, nil
}

func (r *fakeMemberRepo) UpdateRole(_ context.Context, tenantID, memberID string, expectedSeq int64, roleID *string) (organizations.Member, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	m, ok := r.members[memberID]
	if !ok || m.TenantID != tenantID {
		return organizations.Member{}, organizations.ErrNotFound
	}
	if m.RowSeq != expectedSeq {
		return organizations.Member{}, organizations.ErrETagMismatch
	}
	m.RoleID = roleID
	m.RowSeq++
	r.members[memberID] = m
	return m, nil
}

func (r *fakeMemberRepo) Remove(_ context.Context, tenantID, memberID string, expectedSeq int64) (organizations.Member, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	m, ok := r.members[memberID]
	if !ok || m.TenantID != tenantID {
		return organizations.Member{}, organizations.ErrNotFound
	}
	if m.RowSeq != expectedSeq {
		return organizations.Member{}, organizations.ErrETagMismatch
	}
	now := time.Now()
	m.Status = organizations.MemberStatusRemoved
	m.RemovedAt = &now
	m.RowSeq++
	r.members[memberID] = m
	return m, nil
}

func (r *fakeMemberRepo) CountActive(_ context.Context, organizationID string) (int64, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	var n int64
	for _, m := range r.members {
		if m.OrganizationID == organizationID && m.Status == organizations.MemberStatusActive {
			n++
		}
	}
	return n, nil
}

type fakeInvitationRepo struct {
	mu     sync.Mutex
	invs   map[string]organizations.Invitation
	byHash map[string]string // hex(tokenHash) -> invID
}

func newFakeInvitationRepo() *fakeInvitationRepo {
	return &fakeInvitationRepo{
		invs:   map[string]organizations.Invitation{},
		byHash: map[string]string{},
	}
}

func bytesKey(b []byte) string {
	return string(b)
}

func (r *fakeInvitationRepo) Create(_ context.Context, inv organizations.Invitation) (organizations.Invitation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.invs[inv.ID] = inv
	r.byHash[bytesKey(inv.TokenHash)] = inv.ID
	return inv, nil
}

func (r *fakeInvitationRepo) Get(_ context.Context, tenantID, invitationID string) (organizations.Invitation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	inv, ok := r.invs[invitationID]
	if !ok || inv.TenantID != tenantID {
		return organizations.Invitation{}, organizations.ErrNotFound
	}
	return inv, nil
}

func (r *fakeInvitationRepo) GetByTokenHash(_ context.Context, tokenHash []byte) (organizations.Invitation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	id, ok := r.byHash[bytesKey(tokenHash)]
	if !ok {
		return organizations.Invitation{}, organizations.ErrNotFound
	}
	return r.invs[id], nil
}

func (r *fakeInvitationRepo) GetPendingByEmailHash(_ context.Context, organizationID string, emailHash []byte) (organizations.Invitation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, inv := range r.invs {
		if inv.OrganizationID != organizationID || inv.Status != organizations.InvitationStatusPending {
			continue
		}
		if string(inv.InviteeEmailHash) == string(emailHash) {
			return inv, nil
		}
	}
	return organizations.Invitation{}, organizations.ErrNotFound
}

func (r *fakeInvitationRepo) List(_ context.Context, tenantID, organizationID string, _ int) ([]organizations.Invitation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := []organizations.Invitation{}
	for _, inv := range r.invs {
		if inv.TenantID == tenantID && inv.OrganizationID == organizationID {
			out = append(out, inv)
		}
	}
	return out, nil
}

func (r *fakeInvitationRepo) MarkAccepted(_ context.Context, invitationID, acceptedByUserID string) (organizations.Invitation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	inv, ok := r.invs[invitationID]
	if !ok || inv.Status != organizations.InvitationStatusPending {
		return organizations.Invitation{}, organizations.ErrInvitationConsumed
	}
	inv.Status = organizations.InvitationStatusAccepted
	now := time.Now()
	inv.AcceptedAt = &now
	inv.AcceptedByUserID = &acceptedByUserID
	r.invs[invitationID] = inv
	return inv, nil
}

func (r *fakeInvitationRepo) MarkRevoked(_ context.Context, tenantID, invitationID string, expectedSeq int64, revokedByUserID string) (organizations.Invitation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	inv, ok := r.invs[invitationID]
	if !ok || inv.TenantID != tenantID {
		return organizations.Invitation{}, organizations.ErrNotFound
	}
	if inv.Status != organizations.InvitationStatusPending {
		return organizations.Invitation{}, organizations.ErrInvitationConsumed
	}
	if inv.RowSeq != expectedSeq {
		return organizations.Invitation{}, organizations.ErrETagMismatch
	}
	inv.Status = organizations.InvitationStatusRevoked
	now := time.Now()
	inv.RevokedAt = &now
	inv.RevokedByUserID = &revokedByUserID
	inv.RowSeq++
	r.invs[invitationID] = inv
	return inv, nil
}

func (r *fakeInvitationRepo) ExpireOverdue(_ context.Context, now time.Time) ([]organizations.ExpiredRow, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	var out []organizations.ExpiredRow
	for id, inv := range r.invs {
		if inv.Status == organizations.InvitationStatusPending && inv.ExpiresAt.Before(now) {
			inv.Status = organizations.InvitationStatusExpired
			r.invs[id] = inv
			out = append(out, organizations.ExpiredRow{
				InvitationID:   inv.ID,
				TenantID:       inv.TenantID,
				OrganizationID: inv.OrganizationID,
			})
		}
	}
	return out, nil
}

// fakeHasher is a deterministic in-memory hasher. Same key as Identity's
// StaticEmailHasher dev-default; tests only.
type fakeHasher struct{}

func (fakeHasher) Normalise(s string) string {
	// Match HMACEmailHasher.Normalise behaviour.
	return strings.ToLower(strings.TrimSpace(s))
}

func (fakeHasher) Hash(_ context.Context, _, email string) ([]byte, error) {
	// Mimic a hash via straight bytes. Sufficient for uniqueness tests
	// because the fake compares byte-equality.
	return []byte("hash:" + strings.ToLower(strings.TrimSpace(email))), nil
}

type fakeNotifier struct {
	mu    sync.Mutex
	calls []organizations.SendInvitationInput
	err   error
}

func (n *fakeNotifier) SendInvitation(_ context.Context, in organizations.SendInvitationInput) error {
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.err != nil {
		return n.err
	}
	n.calls = append(n.calls, in)
	return nil
}

type fakeTenants struct {
	multiOrg bool
	name     string
}

func (f *fakeTenants) GetTenantBasic(_ context.Context, tenantID string) (organizations.TenantBasic, error) {
	return organizations.TenantBasic{
		ID:       tenantID,
		Name:     f.name,
		MultiOrg: f.multiOrg,
	}, nil
}

type fakeUsers struct {
	users map[string]organizations.UserInfo // userID -> info
}

func (f *fakeUsers) LookupUser(_ context.Context, _, userID string) (organizations.UserInfo, error) {
	u, ok := f.users[userID]
	if !ok {
		return organizations.UserInfo{}, errors.New("user not found")
	}
	return u, nil
}

type capturedEvents struct {
	mu     sync.Mutex
	events []string
}

func (c *capturedEvents) Publish(_ context.Context, eventType, _ string, _ map[string]any) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.events = append(c.events, eventType)
	return nil
}

func (c *capturedEvents) has(t string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	for _, e := range c.events {
		if e == t {
			return true
		}
	}
	return false
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

const (
	fixtureTenant     = "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	fixtureUserA      = "user_01HAAAAAAAAAAAAAAAAAAAAA00"
	fixtureUserB      = "user_01HAAAAAAAAAAAAAAAAAAAAA01"
	fixtureEmailA     = "alice@example.com"
	fixtureEmailB     = "bob@example.com"
	fixtureDeployment = "dep_test"
)

type harness struct {
	svc      *organizations.Service
	orgRepo  *fakeOrgRepo
	memRepo  *fakeMemberRepo
	invRepo  *fakeInvitationRepo
	notifier *fakeNotifier
	tenants  *fakeTenants
	users    *fakeUsers
	events   *capturedEvents
}

func newHarness(t *testing.T) *harness {
	t.Helper()
	h := &harness{
		orgRepo:  newFakeOrgRepo(),
		memRepo:  newFakeMemberRepo(),
		invRepo:  newFakeInvitationRepo(),
		notifier: &fakeNotifier{},
		tenants:  &fakeTenants{multiOrg: false, name: "Acme"},
		users: &fakeUsers{users: map[string]organizations.UserInfo{
			fixtureUserA: {UserID: fixtureUserA, Email: fixtureEmailA, Name: "Alice"},
			fixtureUserB: {UserID: fixtureUserB, Email: fixtureEmailB, Name: "Bob"},
		}},
		events: &capturedEvents{},
	}
	h.svc = organizations.NewService(organizations.Config{
		OrganizationRepo: h.orgRepo,
		MemberRepo:       h.memRepo,
		InvitationRepo:   h.invRepo,
		EmailHasher:      fakeHasher{},
		Notifier:         h.notifier,
		Tenants:          h.tenants,
		Users:            h.users,
		Events:           h.events,
		DeploymentID:     fixtureDeployment,
		PublicBaseURL:    "https://dev.example.saas.test",
	})
	return h
}

func withTenant(tenantID string) context.Context {
	return auth.ContextWithTenant(context.Background(), tenantID)
}

func withPrincipal(tenantID, userID string) context.Context {
	ctx := auth.ContextWithTenant(context.Background(), tenantID)
	return auth.WithPrincipal(ctx, auth.Principal{
		ActorType: auth.ActorUser,
		ActorID:   userID,
		TenantID:  tenantID,
	})
}

// ---------------------------------------------------------------------------
// Organizations
// ---------------------------------------------------------------------------

func TestService_AutoCreateDefault_Idempotent(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant(fixtureTenant)
	o, err := h.svc.AutoCreateDefault(ctx, fixtureTenant)
	if err != nil {
		t.Fatalf("first auto-create: %v", err)
	}
	if o.Slug != organizations.DefaultOrganizationSlug {
		t.Fatalf("expected default slug, got %q", o.Slug)
	}
	// Second call returns the same org without error.
	o2, err := h.svc.AutoCreateDefault(ctx, fixtureTenant)
	if err != nil {
		t.Fatalf("second auto-create: %v", err)
	}
	if o2.ID != o.ID {
		t.Fatalf("second call created a new org: %q vs %q", o2.ID, o.ID)
	}
	if !h.events.has("organization.created") {
		t.Fatalf("expected organization.created event")
	}
}

func TestService_CreateOrganization_MultiOrgDisabled(t *testing.T) {
	h := newHarness(t)
	// multi_org defaults to false in the fixture.
	ctx := withPrincipal(fixtureTenant, fixtureUserA)
	_, err := h.svc.CreateOrganization(ctx, fixtureTenant, organizations.CreateOrganizationInput{
		Slug: "team-2",
		Name: "Team Two",
	})
	if !errors.Is(err, organizations.ErrMultiOrgDisabled) {
		t.Fatalf("expected ErrMultiOrgDisabled, got %v", err)
	}
}

func TestService_CreateOrganization_MultiOrgEnabled(t *testing.T) {
	h := newHarness(t)
	h.tenants.multiOrg = true
	ctx := withPrincipal(fixtureTenant, fixtureUserA)
	o, err := h.svc.CreateOrganization(ctx, fixtureTenant, organizations.CreateOrganizationInput{
		Slug: "team-2",
		Name: "Team Two",
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if o.Slug != "team-2" {
		t.Fatalf("got slug %q", o.Slug)
	}
}

// ---------------------------------------------------------------------------
// Invitation flow
// ---------------------------------------------------------------------------

func TestService_Invitation_HappyPath(t *testing.T) {
	h := newHarness(t)
	// Seed default org.
	org, _ := h.svc.AutoCreateDefault(withTenant(fixtureTenant), fixtureTenant)

	ctxA := withPrincipal(fixtureTenant, fixtureUserA)
	inv, token, err := h.svc.CreateInvitation(ctxA, fixtureTenant, org.ID, organizations.CreateInvitationInput{
		InviteeEmail: fixtureEmailB,
	})
	if err != nil {
		t.Fatalf("create invitation: %v", err)
	}
	if token == "" {
		t.Fatalf("expected non-empty plaintext token in return value")
	}
	if inv.InviteeEmail != "" {
		t.Fatalf("expected service to clear plaintext invitee email on the returned struct")
	}
	if inv.TokenPrefix == "" {
		t.Fatalf("expected token prefix to be populated")
	}
	if len(inv.TokenHash) != 32 {
		t.Fatalf("expected 32-byte sha256 token hash, got %d", len(inv.TokenHash))
	}
	if !h.events.has("invitation.created") || !h.events.has("member.invited") {
		t.Fatalf("expected invitation.created + member.invited events")
	}
	if len(h.notifier.calls) != 1 {
		t.Fatalf("expected one SendInvitation call, got %d", len(h.notifier.calls))
	}

	// Bob accepts.
	ctxB := withPrincipal(fixtureTenant, fixtureUserB)
	member, err := h.svc.AcceptInvitation(ctxB, token)
	if err != nil {
		t.Fatalf("accept: %v", err)
	}
	if member.UserID != fixtureUserB || member.OrganizationID != org.ID {
		t.Fatalf("unexpected member: %+v", member)
	}
	if !h.events.has("invitation.accepted") || !h.events.has("member.joined") {
		t.Fatalf("expected accepted + joined events")
	}

	// Re-accept must fail with ErrInvitationConsumed.
	if _, err := h.svc.AcceptInvitation(ctxB, token); !errors.Is(err, organizations.ErrInvitationConsumed) {
		t.Fatalf("expected ErrInvitationConsumed on re-accept, got %v", err)
	}
}

func TestService_Invitation_AcceptWrongEmail_403(t *testing.T) {
	h := newHarness(t)
	org, _ := h.svc.AutoCreateDefault(withTenant(fixtureTenant), fixtureTenant)
	ctxA := withPrincipal(fixtureTenant, fixtureUserA)
	_, token, err := h.svc.CreateInvitation(ctxA, fixtureTenant, org.ID, organizations.CreateInvitationInput{
		InviteeEmail: "someone-else@example.com",
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	ctxB := withPrincipal(fixtureTenant, fixtureUserB)
	if _, err := h.svc.AcceptInvitation(ctxB, token); !errors.Is(err, organizations.ErrEmailMismatch) {
		t.Fatalf("expected ErrEmailMismatch, got %v", err)
	}
}

func TestService_Invitation_AcceptInvalidToken(t *testing.T) {
	h := newHarness(t)
	ctxB := withPrincipal(fixtureTenant, fixtureUserB)
	_, err := h.svc.AcceptInvitation(ctxB, "not-a-real-token-just-garbage")
	if !errors.Is(err, organizations.ErrInvalidToken) {
		t.Fatalf("expected ErrInvalidToken, got %v", err)
	}
}

func TestService_Invitation_AcceptCrossTenant(t *testing.T) {
	h := newHarness(t)
	org, _ := h.svc.AutoCreateDefault(withTenant(fixtureTenant), fixtureTenant)
	ctxA := withPrincipal(fixtureTenant, fixtureUserA)
	_, token, err := h.svc.CreateInvitation(ctxA, fixtureTenant, org.ID, organizations.CreateInvitationInput{
		InviteeEmail: fixtureEmailB,
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	// A caller in a different tenant tries to accept.
	otherTenant := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"
	ctxOther := withPrincipal(otherTenant, fixtureUserB)
	if _, err := h.svc.AcceptInvitation(ctxOther, token); !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("expected ErrCrossTenant on cross-tenant accept, got %v", err)
	}
}

func TestService_Invitation_AcceptExpired(t *testing.T) {
	h := newHarness(t)
	org, _ := h.svc.AutoCreateDefault(withTenant(fixtureTenant), fixtureTenant)
	ctxA := withPrincipal(fixtureTenant, fixtureUserA)
	_, token, err := h.svc.CreateInvitation(ctxA, fixtureTenant, org.ID, organizations.CreateInvitationInput{
		InviteeEmail: fixtureEmailB,
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	// Fast-forward the clock past expiry.
	h.svc.WithClock(func() time.Time {
		return time.Now().Add(organizations.DefaultInvitationTTL + time.Hour)
	})
	ctxB := withPrincipal(fixtureTenant, fixtureUserB)
	if _, err := h.svc.AcceptInvitation(ctxB, token); !errors.Is(err, organizations.ErrInvitationExpired) {
		t.Fatalf("expected ErrInvitationExpired, got %v", err)
	}
}

func TestService_Invitation_DuplicatePending(t *testing.T) {
	h := newHarness(t)
	org, _ := h.svc.AutoCreateDefault(withTenant(fixtureTenant), fixtureTenant)
	ctxA := withPrincipal(fixtureTenant, fixtureUserA)
	_, _, err := h.svc.CreateInvitation(ctxA, fixtureTenant, org.ID, organizations.CreateInvitationInput{
		InviteeEmail: fixtureEmailB,
	})
	if err != nil {
		t.Fatalf("first invite: %v", err)
	}
	_, _, err = h.svc.CreateInvitation(ctxA, fixtureTenant, org.ID, organizations.CreateInvitationInput{
		InviteeEmail: fixtureEmailB,
	})
	if !errors.Is(err, organizations.ErrPendingInvitationExists) {
		t.Fatalf("expected ErrPendingInvitationExists, got %v", err)
	}
}

func TestService_Invitation_RevokeFlow(t *testing.T) {
	h := newHarness(t)
	org, _ := h.svc.AutoCreateDefault(withTenant(fixtureTenant), fixtureTenant)
	ctxA := withPrincipal(fixtureTenant, fixtureUserA)
	inv, token, err := h.svc.CreateInvitation(ctxA, fixtureTenant, org.ID, organizations.CreateInvitationInput{
		InviteeEmail: fixtureEmailB,
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := h.svc.RevokeInvitation(ctxA, fixtureTenant, inv.ID, inv.RowSeq); err != nil {
		t.Fatalf("revoke: %v", err)
	}
	if !h.events.has("invitation.revoked") {
		t.Fatalf("expected invitation.revoked event")
	}
	// Re-accept the revoked invitation must fail.
	ctxB := withPrincipal(fixtureTenant, fixtureUserB)
	if _, err := h.svc.AcceptInvitation(ctxB, token); !errors.Is(err, organizations.ErrInvitationConsumed) {
		t.Fatalf("expected ErrInvitationConsumed on revoked accept, got %v", err)
	}
}

func TestService_Invitation_SweepExpired(t *testing.T) {
	h := newHarness(t)
	org, _ := h.svc.AutoCreateDefault(withTenant(fixtureTenant), fixtureTenant)
	ctxA := withPrincipal(fixtureTenant, fixtureUserA)
	_, _, err := h.svc.CreateInvitation(ctxA, fixtureTenant, org.ID, organizations.CreateInvitationInput{
		InviteeEmail: fixtureEmailB,
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	// Force clock past expiry.
	h.svc.WithClock(func() time.Time {
		return time.Now().Add(organizations.DefaultInvitationTTL + time.Hour)
	})
	n, err := h.svc.SweepExpiredInvitations(context.Background())
	if err != nil {
		t.Fatalf("sweep: %v", err)
	}
	if n != 1 {
		t.Fatalf("expected 1 row flipped, got %d", n)
	}
	if !h.events.has("invitation.expired") {
		t.Fatalf("expected invitation.expired event")
	}
}

func TestService_Invitation_TokenComparisonIsConstantTime(t *testing.T) {
	// This is a static/source-level check: the package must import
	// crypto/subtle and reference ConstantTimeCompare. The actual timing
	// behaviour is provided by the stdlib; we just guarantee the call.
	if !packageReferencesConstantTime() {
		t.Fatal("invite.go must use crypto/subtle.ConstantTimeCompare for token + email comparisons")
	}
}
