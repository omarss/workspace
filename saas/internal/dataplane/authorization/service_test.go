package authorization_test

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/casbin/casbin/v2/model"
	"github.com/casbin/casbin/v2/persist"

	"github.com/omarss/saas/internal/dataplane/authorization"
	"github.com/omarss/saas/internal/platform/auth"
)

// inMemoryAdapter is a tiny persist.Adapter that keeps policy rules in
// memory. We don't use the upstream file-adapter because it requires a
// real file path; a per-test adapter keeps the test surface stable.
type inMemoryAdapter struct {
	policies [][]string // ptype + the rule values
}

func newInMemoryAdapter() *inMemoryAdapter { return &inMemoryAdapter{} }

func (a *inMemoryAdapter) LoadPolicy(m model.Model) error {
	for _, line := range a.policies {
		if err := persist.LoadPolicyLine(strings.Join(line, ", "), m); err != nil {
			return err
		}
	}
	return nil
}

func (a *inMemoryAdapter) SavePolicy(_ model.Model) error { return nil }

func (a *inMemoryAdapter) AddPolicy(_ string, ptype string, rule []string) error {
	a.policies = append(a.policies, append([]string{ptype}, rule...))
	return nil
}

func (a *inMemoryAdapter) RemovePolicy(_ string, ptype string, rule []string) error {
	for i, row := range a.policies {
		if row[0] != ptype || len(row)-1 != len(rule) {
			continue
		}
		match := true
		for j, v := range rule {
			if row[j+1] != v {
				match = false
				break
			}
		}
		if match {
			a.policies = append(a.policies[:i], a.policies[i+1:]...)
			return nil
		}
	}
	return nil
}

func (a *inMemoryAdapter) RemoveFilteredPolicy(_ string, ptype string, fieldIndex int, fieldValues ...string) error {
	kept := a.policies[:0]
	for _, row := range a.policies {
		if row[0] != ptype {
			kept = append(kept, row)
			continue
		}
		match := true
		for i, v := range fieldValues {
			idx := fieldIndex + i + 1
			if idx >= len(row) || row[idx] != v {
				match = false
				break
			}
		}
		if !match {
			kept = append(kept, row)
		}
	}
	a.policies = kept
	return nil
}

// ---------------------------------------------------------------------------
// Test fixtures + in-memory fakes.
// ---------------------------------------------------------------------------

const (
	fixtureTenant   = "tenant_01HXAAAAAAAAAAAAAAAAAAAAAA"
	fixtureTenantB  = "tenant_01HXBBBBBBBBBBBBBBBBBBBBBB"
	fixtureMemberA  = "member_01HXAAAAAAAAAAAAAAAAAAAAAA"
	fixtureMemberB  = "member_01HXBBBBBBBBBBBBBBBBBBBBBB"
	fixturePermRead = "perm_tenant_read"
	fixturePermWrt  = "perm_tenant_write"
)

func withTenant(tenantID string) context.Context {
	ctx := context.Background()
	ctx = auth.WithPrincipal(ctx, auth.Principal{
		ActorType: auth.ActorUser,
		ActorID:   "user_test",
		TenantID:  tenantID,
	})
	return ctx
}

type memoryRoleRepo struct {
	rows map[string]authorization.Role
}

func newMemoryRoleRepo() *memoryRoleRepo {
	return &memoryRoleRepo{rows: map[string]authorization.Role{}}
}

func (m *memoryRoleRepo) Create(_ context.Context, r authorization.Role) (authorization.Role, error) {
	r.RowSeq = 1
	r.CreatedAt = time.Now().UTC()
	r.UpdatedAt = r.CreatedAt
	m.rows[r.ID] = r
	return r, nil
}

func (m *memoryRoleRepo) Get(_ context.Context, tenantID, roleID string) (authorization.Role, error) {
	r, ok := m.rows[roleID]
	if !ok || r.TenantID != tenantID || r.DeletedAt != nil {
		return authorization.Role{}, authorization.ErrRoleNotFound
	}
	return r, nil
}

func (m *memoryRoleRepo) List(_ context.Context, tenantID string, _ int) ([]authorization.Role, error) {
	out := []authorization.Role{}
	for _, r := range m.rows {
		if r.TenantID == tenantID && r.DeletedAt == nil {
			out = append(out, r)
		}
	}
	return out, nil
}

func (m *memoryRoleRepo) Update(_ context.Context, tenantID, roleID string, expectedSeq int64, patch authorization.RolePatch) (authorization.Role, error) {
	r, ok := m.rows[roleID]
	if !ok || r.TenantID != tenantID || r.DeletedAt != nil {
		return authorization.Role{}, authorization.ErrRoleNotFound
	}
	if r.RowSeq != expectedSeq {
		return authorization.Role{}, authorization.ErrETagMismatch
	}
	if patch.Name != nil {
		r.Name = *patch.Name
	}
	if patch.Description != nil {
		r.Description = *patch.Description
	}
	if patch.Metadata != nil {
		r.Metadata = patch.Metadata
	}
	r.RowSeq++
	r.UpdatedAt = time.Now().UTC()
	m.rows[roleID] = r
	return r, nil
}

// snapshot returns every role for tenantID. Test-only helper; the
// subscriber test uses it to assert exactly the three system roles land
// after a tenant.created event. No error return (the in-memory store
// cannot fail), but the signature stays close to the real List for
// symmetry with the repo port.
func (m *memoryRoleRepo) snapshot(tenantID string) []authorization.Role {
	out := []authorization.Role{}
	for _, r := range m.rows {
		if r.TenantID == tenantID && r.DeletedAt == nil {
			out = append(out, r)
		}
	}
	return out
}

func (m *memoryRoleRepo) SoftDelete(_ context.Context, tenantID, roleID string, expectedSeq int64) (authorization.Role, error) {
	r, ok := m.rows[roleID]
	if !ok || r.TenantID != tenantID || r.DeletedAt != nil {
		return authorization.Role{}, authorization.ErrRoleNotFound
	}
	if r.RowSeq != expectedSeq {
		return authorization.Role{}, authorization.ErrETagMismatch
	}
	now := time.Now().UTC()
	r.DeletedAt = &now
	r.RowSeq++
	m.rows[roleID] = r
	return r, nil
}

type memoryPermRepo struct{ rows []authorization.Permission }

func newMemoryPermRepo() *memoryPermRepo {
	// Mirrors the deployment-wide permission catalogue seeded by
	// migrations/dataplane/000006_authorization.up.sql so tests
	// exercising the tenant.created subscriber resolve every default
	// system-role permission. Keep in sync with the migration.
	return &memoryPermRepo{rows: []authorization.Permission{
		{ID: fixturePermRead, ResourceType: "tenant", Action: "read", Description: "Read tenant", Module: "tenancy", IsSystem: true},
		{ID: fixturePermWrt, ResourceType: "tenant", Action: "write", Description: "Write tenant", Module: "tenancy", IsSystem: true},
		{ID: "perm_tenants_impersonate", ResourceType: "tenants", Action: "impersonate", Module: "tenancy", IsSystem: true},
		{ID: "perm_organization_read", ResourceType: "organization", Action: "read", Module: "organizations", IsSystem: true},
		{ID: "perm_organization_write", ResourceType: "organization", Action: "write", Module: "organizations", IsSystem: true},
		{ID: "perm_organization_delete", ResourceType: "organization", Action: "delete", Module: "organizations", IsSystem: true},
		{ID: "perm_member_read", ResourceType: "member", Action: "read", Module: "organizations", IsSystem: true},
		{ID: "perm_member_write", ResourceType: "member", Action: "write", Module: "organizations", IsSystem: true},
		{ID: "perm_invitation_read", ResourceType: "invitation", Action: "read", Module: "organizations", IsSystem: true},
		{ID: "perm_invitation_write", ResourceType: "invitation", Action: "write", Module: "organizations", IsSystem: true},
		{ID: "perm_user_read", ResourceType: "user", Action: "read", Module: "identity", IsSystem: true},
		{ID: "perm_user_write", ResourceType: "user", Action: "write", Module: "identity", IsSystem: true},
		{ID: "perm_user_disable", ResourceType: "user", Action: "disable", Module: "identity", IsSystem: true},
		{ID: "perm_role_read", ResourceType: "role", Action: "read", Module: "authorization", IsSystem: true},
		{ID: "perm_role_write", ResourceType: "role", Action: "write", Module: "authorization", IsSystem: true},
		{ID: "perm_role_delete", ResourceType: "role", Action: "delete", Module: "authorization", IsSystem: true},
		{ID: "perm_role_assign", ResourceType: "role", Action: "assign", Module: "authorization", IsSystem: true},
		{ID: "perm_apikey_read", ResourceType: "apikey", Action: "read", Module: "apikeys", IsSystem: true},
		{ID: "perm_apikey_write", ResourceType: "apikey", Action: "write", Module: "apikeys", IsSystem: true},
		{ID: "perm_audit_read", ResourceType: "audit", Action: "read", Module: "audit", IsSystem: true},
		{ID: "perm_notification_read", ResourceType: "notification", Action: "read", Module: "notifications", IsSystem: true},
		{ID: "perm_notification_send", ResourceType: "notification", Action: "send", Module: "notifications", IsSystem: true},
		{ID: "perm_notification_channel_read", ResourceType: "notification_channel", Action: "read", Module: "notifications", IsSystem: true},
		{ID: "perm_notification_channel_write", ResourceType: "notification_channel", Action: "write", Module: "notifications", IsSystem: true},
	}}
}

func (m *memoryPermRepo) List(_ context.Context) ([]authorization.Permission, error) {
	return append([]authorization.Permission{}, m.rows...), nil
}

func (m *memoryPermRepo) Get(_ context.Context, id string) (authorization.Permission, error) {
	for _, p := range m.rows {
		if p.ID == id {
			return p, nil
		}
	}
	return authorization.Permission{}, authorization.ErrPermissionNotFound
}

type memoryMRRepo struct {
	rows map[string]authorization.MemberRole
}

func newMemoryMRRepo() *memoryMRRepo {
	return &memoryMRRepo{rows: map[string]authorization.MemberRole{}}
}

func mrKey(memberID, roleID string) string { return memberID + "::" + roleID }

func (m *memoryMRRepo) Assign(_ context.Context, mr authorization.MemberRole) (authorization.MemberRole, error) {
	mr.AssignedAt = time.Now().UTC()
	m.rows[mrKey(mr.MemberID, mr.RoleID)] = mr
	return mr, nil
}

func (m *memoryMRRepo) Unassign(_ context.Context, memberID, roleID string) (bool, error) {
	k := mrKey(memberID, roleID)
	if _, ok := m.rows[k]; ok {
		delete(m.rows, k)
		return true, nil
	}
	return false, nil
}

func (m *memoryMRRepo) List(_ context.Context, memberID string) ([]authorization.MemberRole, error) {
	out := []authorization.MemberRole{}
	for _, mr := range m.rows {
		if mr.MemberID == memberID {
			out = append(out, mr)
		}
	}
	return out, nil
}

type memoryMemberLookup struct{ tenants map[string]string }

func newMemoryMemberLookup(tenants map[string]string) *memoryMemberLookup {
	return &memoryMemberLookup{tenants: tenants}
}

func (m *memoryMemberLookup) GetMemberTenant(_ context.Context, memberID string) (string, error) {
	if t, ok := m.tenants[memberID]; ok {
		return t, nil
	}
	return "", authorization.ErrMemberNotFound
}

type recordingEvents struct {
	events []recordedEvent
}

type recordedEvent struct {
	Type    string
	Tenant  string
	Payload map[string]any
}

func (r *recordingEvents) Publish(_ context.Context, eventType, tenantID string, payload map[string]any) error {
	r.events = append(r.events, recordedEvent{Type: eventType, Tenant: tenantID, Payload: payload})
	return nil
}

func (r *recordingEvents) countOfType(t string) int {
	n := 0
	for _, ev := range r.events {
		if ev.Type == t {
			n++
		}
	}
	return n
}

// harness assembles the service with fakes + a real Casbin enforcer
// backed by an in-memory file adapter. The model file is the embedded
// rbac.conf so the matcher under test is the production one.
type harness struct {
	svc         *authorization.Service
	roles       *memoryRoleRepo
	memberRoles *memoryMRRepo
	enforcer    *authorization.CasbinEnforcer
	events      *recordingEvents
	members     *memoryMemberLookup
}

func newHarness(t *testing.T) *harness {
	t.Helper()
	a := newInMemoryAdapter()
	enforcer, err := authorization.NewCasbinEnforcerFromAdapter(a)
	if err != nil {
		t.Fatalf("enforcer: %v", err)
	}
	roles := newMemoryRoleRepo()
	mrRepo := newMemoryMRRepo()
	events := &recordingEvents{}
	members := newMemoryMemberLookup(map[string]string{
		fixtureMemberA: fixtureTenant,
		fixtureMemberB: fixtureTenantB,
	})
	svc := authorization.NewService(authorization.Config{
		RoleRepo:       roles,
		PermissionRepo: newMemoryPermRepo(),
		MemberRoleRepo: mrRepo,
		PolicyStore:    enforcer,
		MemberLookup:   members,
		Events:         events,
	})
	return &harness{svc: svc, roles: roles, memberRoles: mrRepo, enforcer: enforcer, events: events, members: members}
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

func TestService_CreateRole_Allows_SameTenant(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant(fixtureTenant)
	r, err := h.svc.CreateRole(ctx, fixtureTenant, authorization.CreateRoleInput{
		Name:        "tenant_admin",
		Description: "Admin role",
		Permissions: []string{fixturePermRead, fixturePermWrt},
	})
	if err != nil {
		t.Fatalf("CreateRole: %v", err)
	}
	if r.ID == "" || !strings.HasPrefix(r.ID, "role_") {
		t.Fatalf("CreateRole returned bad id %q", r.ID)
	}
	if h.events.countOfType("role.created") != 1 {
		t.Fatalf("expected one role.created event, got %d", h.events.countOfType("role.created"))
	}
}

func TestService_CreateRole_RejectsCrossTenant(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant(fixtureTenant)
	_, err := h.svc.CreateRole(ctx, fixtureTenantB, authorization.CreateRoleInput{Name: "x"})
	if !errors.Is(err, auth.ErrCrossTenant) {
		t.Fatalf("expected ErrCrossTenant, got %v", err)
	}
}

func TestService_CreateRole_RejectsMissingContext(t *testing.T) {
	h := newHarness(t)
	_, err := h.svc.CreateRole(context.Background(), fixtureTenant, authorization.CreateRoleInput{Name: "x"})
	if !errors.Is(err, auth.ErrUnauthorized) {
		t.Fatalf("expected ErrUnauthorized, got %v", err)
	}
}

func TestService_AddPolicy_RejectsWildcardDomain(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant("*")
	_, err := h.svc.CreateRole(ctx, "*", authorization.CreateRoleInput{Name: "x"})
	if !errors.Is(err, authorization.ErrWildcardDomain) && !errors.Is(err, auth.ErrCrossTenant) {
		// AssertTenant passes if the caller's tenant matches the
		// resource tenant; both are "*" here so AssertTenant returns
		// nil and the wildcard guard at the policy layer fires.
		t.Fatalf("expected ErrWildcardDomain, got %v", err)
	}

	// Bypass AssertTenant by going directly to the enforcer — this
	// exercises the policy-layer guard. Even with a valid tenant in
	// context, the enforcer refuses domain=*.
	if err := h.enforcer.AddRolePolicy(ctx, "role_x", "*", "tenant", "read"); !errors.Is(err, authorization.ErrWildcardDomain) {
		t.Fatalf("expected ErrWildcardDomain from enforcer, got %v", err)
	}

	// Also reject a role named "*" — defence in depth at the validator.
	ctx2 := withTenant(fixtureTenant)
	_, err = h.svc.CreateRole(ctx2, fixtureTenant, authorization.CreateRoleInput{Name: "*"})
	if !errors.Is(err, authorization.ErrWildcardDomain) && !errors.Is(err, authorization.ErrInvalidRoleName) {
		t.Fatalf("expected ErrWildcardDomain or ErrInvalidRoleName, got %v", err)
	}
}

func TestService_Check_AllowedAndDeniedAuditEmitted(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant(fixtureTenant)

	// Seed a role granting tenant.read.
	role, err := h.svc.CreateRole(ctx, fixtureTenant, authorization.CreateRoleInput{
		Name:        "tenant_admin",
		Permissions: []string{fixturePermRead},
	})
	if err != nil {
		t.Fatalf("CreateRole: %v", err)
	}
	// Assign the role to the member.
	if _, err := h.svc.AssignMemberRole(ctx, fixtureTenant, fixtureMemberA, role.ID); err != nil {
		t.Fatalf("AssignMemberRole: %v", err)
	}

	// Allowed check: tenant.read → allowed.
	resp, err := h.svc.Check(ctx, fixtureTenant, fixtureMemberA, "tenant.read")
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	if !resp.Allowed {
		t.Fatalf("expected allowed=true, got %+v", resp)
	}
	if resp.ViaRole != role.ID {
		t.Fatalf("expected via_role=%s got %q", role.ID, resp.ViaRole)
	}

	// Denied check: tenant.write → not granted.
	resp2, err := h.svc.Check(ctx, fixtureTenant, fixtureMemberA, "tenant.write")
	if err != nil {
		t.Fatalf("Check (denied): %v", err)
	}
	if resp2.Allowed {
		t.Fatalf("expected denied, got allowed")
	}

	// The denied check must emit authorization.denied.
	if h.events.countOfType("authorization.denied") != 1 {
		t.Fatalf("expected 1 authorization.denied event, got %d", h.events.countOfType("authorization.denied"))
	}
}

func TestService_Check_RejectsCrossTenantMember(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant(fixtureTenant)

	// fixtureMemberB belongs to tenant_B; the caller is in tenant_A.
	// Even though AssertTenant passes (caller asks about its own
	// tenant), the member-tenant cross-check refuses.
	resp, err := h.svc.Check(ctx, fixtureTenant, fixtureMemberB, "tenant.read")
	if !errors.Is(err, authorization.ErrCrossTenantMember) {
		t.Fatalf("expected ErrCrossTenantMember, got %v (resp=%+v)", err, resp)
	}
	// The denied event records the reason.
	if h.events.countOfType("authorization.denied") != 1 {
		t.Fatalf("expected 1 authorization.denied event, got %d", h.events.countOfType("authorization.denied"))
	}
}

func TestService_Check_RejectsMissingContext(t *testing.T) {
	h := newHarness(t)
	_, err := h.svc.Check(context.Background(), fixtureTenant, fixtureMemberA, "tenant.read")
	if !errors.Is(err, auth.ErrUnauthorized) {
		t.Fatalf("expected ErrUnauthorized, got %v", err)
	}
}

func TestService_Check_RejectsMalformedPermission(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant(fixtureTenant)
	_, err := h.svc.Check(ctx, fixtureTenant, fixtureMemberA, "tenant")
	if !errors.Is(err, authorization.ErrMalformedPermission) {
		t.Fatalf("expected ErrMalformedPermission, got %v", err)
	}
	_, err = h.svc.Check(ctx, fixtureTenant, fixtureMemberA, "tenant.read.extra")
	if !errors.Is(err, authorization.ErrMalformedPermission) {
		t.Fatalf("expected ErrMalformedPermission on dotted, got %v", err)
	}
}

func TestService_BatchCheck_RejectsOversize(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant(fixtureTenant)
	reqs := make([]authorization.CheckBatchEntry, authorization.MaxBatchCheckSize+1)
	for i := range reqs {
		reqs[i] = authorization.CheckBatchEntry{
			TenantID:   fixtureTenant,
			MemberID:   fixtureMemberA,
			Permission: "tenant.read",
		}
	}
	_, err := h.svc.BatchCheck(ctx, reqs)
	if !errors.Is(err, authorization.ErrBatchTooLarge) {
		t.Fatalf("expected ErrBatchTooLarge, got %v", err)
	}
}

func TestService_AssignMemberRole_RejectsCrossTenantMember(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant(fixtureTenant)
	role, err := h.svc.CreateRole(ctx, fixtureTenant, authorization.CreateRoleInput{Name: "x"})
	if err != nil {
		t.Fatalf("CreateRole: %v", err)
	}
	// memberB belongs to tenant_B — assigning to it via tenant_A's role
	// is a cross-tenant attempt.
	if _, err := h.svc.AssignMemberRole(ctx, fixtureTenant, fixtureMemberB, role.ID); !errors.Is(err, authorization.ErrCrossTenantMember) {
		t.Fatalf("expected ErrCrossTenantMember, got %v", err)
	}
}

func TestService_DeleteRole_RejectsSystemRole(t *testing.T) {
	h := newHarness(t)
	ctx := withTenant(fixtureTenant)
	// Seed a system role directly via the repo so the service doesn't
	// have to expose an IsSystem flag at CreateRole time (system roles
	// are seeded by the tenant.created hook, not via the API).
	r, err := h.roles.Create(ctx, authorization.Role{
		ID:       "role_test_system",
		TenantID: fixtureTenant,
		Name:     "tenant_admin",
		IsSystem: true,
	})
	if err != nil {
		t.Fatalf("seed: %v", err)
	}
	if err := h.svc.DeleteRole(ctx, fixtureTenant, r.ID, r.RowSeq); !errors.Is(err, authorization.ErrSystemRoleImmutable) {
		t.Fatalf("expected ErrSystemRoleImmutable, got %v", err)
	}
}
