package tenancy_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"

	httpapi "github.com/omarss/saas/internal/dataplane/httpapi" // package dataplaneapi
	"github.com/omarss/saas/internal/dataplane/identity"
	"github.com/omarss/saas/internal/dataplane/notifications"
	"github.com/omarss/saas/internal/dataplane/tenancy"
	"github.com/omarss/saas/internal/platform/auth"
)

// strictSrv composes the tenancy handler with a real (but minimally-wired)
// identity handler so the §17.3 matrix exercises the same StrictServerInterface
// the data-plane binary serves. The identity service is wired against an
// in-memory identity repo so the strict interface is fully satisfied without
// dragging Keycloak or a real DB into the tenancy suite.
type strictSrv struct {
	tenants       *tenancy.Handler
	identity      *identity.Handler
	notifications *notifications.Handler
}

// Tenants delegation —————————————————————————————————————————————————————

func (s *strictSrv) ListTenants(ctx context.Context, r httpapi.ListTenantsRequestObject) (httpapi.ListTenantsResponseObject, error) {
	return s.tenants.ListTenants(ctx, r)
}

func (s *strictSrv) CreateTenant(ctx context.Context, r httpapi.CreateTenantRequestObject) (httpapi.CreateTenantResponseObject, error) {
	return s.tenants.CreateTenant(ctx, r)
}

func (s *strictSrv) GetTenant(ctx context.Context, r httpapi.GetTenantRequestObject) (httpapi.GetTenantResponseObject, error) {
	return s.tenants.GetTenant(ctx, r)
}

func (s *strictSrv) UpdateTenant(ctx context.Context, r httpapi.UpdateTenantRequestObject) (httpapi.UpdateTenantResponseObject, error) {
	return s.tenants.UpdateTenant(ctx, r)
}

func (s *strictSrv) DeleteTenant(ctx context.Context, r httpapi.DeleteTenantRequestObject) (httpapi.DeleteTenantResponseObject, error) {
	return s.tenants.DeleteTenant(ctx, r)
}

// Identity delegation —————————————————————————————————————————————————————

func (s *strictSrv) ListUsers(ctx context.Context, r httpapi.ListUsersRequestObject) (httpapi.ListUsersResponseObject, error) {
	return s.identity.ListUsers(ctx, r)
}

func (s *strictSrv) CreateUser(ctx context.Context, r httpapi.CreateUserRequestObject) (httpapi.CreateUserResponseObject, error) {
	return s.identity.CreateUser(ctx, r)
}

func (s *strictSrv) GetUser(ctx context.Context, r httpapi.GetUserRequestObject) (httpapi.GetUserResponseObject, error) {
	return s.identity.GetUser(ctx, r)
}

func (s *strictSrv) UpdateUser(ctx context.Context, r httpapi.UpdateUserRequestObject) (httpapi.UpdateUserResponseObject, error) {
	return s.identity.UpdateUser(ctx, r)
}

func (s *strictSrv) DeleteUser(ctx context.Context, r httpapi.DeleteUserRequestObject) (httpapi.DeleteUserResponseObject, error) {
	return s.identity.DeleteUser(ctx, r)
}

func (s *strictSrv) DisableUser(ctx context.Context, r httpapi.DisableUserRequestObject) (httpapi.DisableUserResponseObject, error) {
	return s.identity.DisableUser(ctx, r)
}

func (s *strictSrv) EnableUser(ctx context.Context, r httpapi.EnableUserRequestObject) (httpapi.EnableUserResponseObject, error) {
	return s.identity.EnableUser(ctx, r)
}

func (s *strictSrv) TriggerPasswordReset(ctx context.Context, r httpapi.TriggerPasswordResetRequestObject) (httpapi.TriggerPasswordResetResponseObject, error) {
	return s.identity.TriggerPasswordReset(ctx, r)
}

func (s *strictSrv) TriggerEmailVerify(ctx context.Context, r httpapi.TriggerEmailVerifyRequestObject) (httpapi.TriggerEmailVerifyResponseObject, error) {
	return s.identity.TriggerEmailVerify(ctx, r)
}

func (s *strictSrv) ListSocialProviders(ctx context.Context, r httpapi.ListSocialProvidersRequestObject) (httpapi.ListSocialProvidersResponseObject, error) {
	return s.identity.ListSocialProviders(ctx, r)
}

func (s *strictSrv) LinkSocialProvider(ctx context.Context, r httpapi.LinkSocialProviderRequestObject) (httpapi.LinkSocialProviderResponseObject, error) {
	return s.identity.LinkSocialProvider(ctx, r)
}

func (s *strictSrv) UnlinkSocialProvider(ctx context.Context, r httpapi.UnlinkSocialProviderRequestObject) (httpapi.UnlinkSocialProviderResponseObject, error) {
	return s.identity.UnlinkSocialProvider(ctx, r)
}

func (s *strictSrv) GetHealthz(_ context.Context, _ httpapi.GetHealthzRequestObject) (httpapi.GetHealthzResponseObject, error) {
	return httpapi.GetHealthz200JSONResponse{Status: httpapi.Ok}, nil
}

// Notifications delegation ————————————————————————————————————————————————

func (s *strictSrv) ListNotificationChannels(ctx context.Context, r httpapi.ListNotificationChannelsRequestObject) (httpapi.ListNotificationChannelsResponseObject, error) {
	return s.notifications.ListNotificationChannels(ctx, r)
}

func (s *strictSrv) CreateNotificationChannel(ctx context.Context, r httpapi.CreateNotificationChannelRequestObject) (httpapi.CreateNotificationChannelResponseObject, error) {
	return s.notifications.CreateNotificationChannel(ctx, r)
}

func (s *strictSrv) GetNotificationChannel(ctx context.Context, r httpapi.GetNotificationChannelRequestObject) (httpapi.GetNotificationChannelResponseObject, error) {
	return s.notifications.GetNotificationChannel(ctx, r)
}

func (s *strictSrv) UpdateNotificationChannel(ctx context.Context, r httpapi.UpdateNotificationChannelRequestObject) (httpapi.UpdateNotificationChannelResponseObject, error) {
	return s.notifications.UpdateNotificationChannel(ctx, r)
}

func (s *strictSrv) DeleteNotificationChannel(ctx context.Context, r httpapi.DeleteNotificationChannelRequestObject) (httpapi.DeleteNotificationChannelResponseObject, error) {
	return s.notifications.DeleteNotificationChannel(ctx, r)
}

func (s *strictSrv) RotateNotificationChannelCredentials(ctx context.Context, r httpapi.RotateNotificationChannelCredentialsRequestObject) (httpapi.RotateNotificationChannelCredentialsResponseObject, error) {
	return s.notifications.RotateNotificationChannelCredentials(ctx, r)
}

func (s *strictSrv) ListNotificationWorkflows(ctx context.Context, r httpapi.ListNotificationWorkflowsRequestObject) (httpapi.ListNotificationWorkflowsResponseObject, error) {
	return s.notifications.ListNotificationWorkflows(ctx, r)
}

func (s *strictSrv) RegisterNotificationWorkflow(ctx context.Context, r httpapi.RegisterNotificationWorkflowRequestObject) (httpapi.RegisterNotificationWorkflowResponseObject, error) {
	return s.notifications.RegisterNotificationWorkflow(ctx, r)
}

func (s *strictSrv) UpdateNotificationWorkflow(ctx context.Context, r httpapi.UpdateNotificationWorkflowRequestObject) (httpapi.UpdateNotificationWorkflowResponseObject, error) {
	return s.notifications.UpdateNotificationWorkflow(ctx, r)
}

func (s *strictSrv) ListNotifications(ctx context.Context, r httpapi.ListNotificationsRequestObject) (httpapi.ListNotificationsResponseObject, error) {
	return s.notifications.ListNotifications(ctx, r)
}

func (s *strictSrv) SendNotification(ctx context.Context, r httpapi.SendNotificationRequestObject) (httpapi.SendNotificationResponseObject, error) {
	return s.notifications.SendNotification(ctx, r)
}

func (s *strictSrv) GetNotification(ctx context.Context, r httpapi.GetNotificationRequestObject) (httpapi.GetNotificationResponseObject, error) {
	return s.notifications.GetNotification(ctx, r)
}

// Organizations delegation — Phase 7 stubs so the §17.3 tenancy matrix
// continues to compile against the post-Phase-7 StrictServerInterface.
// Each stub returns nil so the test, which only exercises tenancy
// endpoints, never invokes them. A future tenancy-vs-orgs cross-matrix
// will replace these with a real organizations.Handler wiring.

func (s *strictSrv) ListOrganizations(_ context.Context, _ httpapi.ListOrganizationsRequestObject) (httpapi.ListOrganizationsResponseObject, error) {
	return nil, nil //nolint:nilnil // unused in tenancy matrix
}

func (s *strictSrv) CreateOrganization(_ context.Context, _ httpapi.CreateOrganizationRequestObject) (httpapi.CreateOrganizationResponseObject, error) {
	return nil, nil //nolint:nilnil
}

func (s *strictSrv) GetOrganization(_ context.Context, _ httpapi.GetOrganizationRequestObject) (httpapi.GetOrganizationResponseObject, error) {
	return nil, nil //nolint:nilnil
}

func (s *strictSrv) UpdateOrganization(_ context.Context, _ httpapi.UpdateOrganizationRequestObject) (httpapi.UpdateOrganizationResponseObject, error) {
	return nil, nil //nolint:nilnil
}

func (s *strictSrv) DeleteOrganization(_ context.Context, _ httpapi.DeleteOrganizationRequestObject) (httpapi.DeleteOrganizationResponseObject, error) {
	return nil, nil //nolint:nilnil
}

func (s *strictSrv) ListMembers(_ context.Context, _ httpapi.ListMembersRequestObject) (httpapi.ListMembersResponseObject, error) {
	return nil, nil //nolint:nilnil
}

func (s *strictSrv) GetMember(_ context.Context, _ httpapi.GetMemberRequestObject) (httpapi.GetMemberResponseObject, error) {
	return nil, nil //nolint:nilnil
}

func (s *strictSrv) UpdateMember(_ context.Context, _ httpapi.UpdateMemberRequestObject) (httpapi.UpdateMemberResponseObject, error) {
	return nil, nil //nolint:nilnil
}

func (s *strictSrv) RemoveMember(_ context.Context, _ httpapi.RemoveMemberRequestObject) (httpapi.RemoveMemberResponseObject, error) {
	return nil, nil //nolint:nilnil
}

func (s *strictSrv) ListInvitations(_ context.Context, _ httpapi.ListInvitationsRequestObject) (httpapi.ListInvitationsResponseObject, error) {
	return nil, nil //nolint:nilnil
}

func (s *strictSrv) CreateInvitation(_ context.Context, _ httpapi.CreateInvitationRequestObject) (httpapi.CreateInvitationResponseObject, error) {
	return nil, nil //nolint:nilnil
}

func (s *strictSrv) GetInvitation(_ context.Context, _ httpapi.GetInvitationRequestObject) (httpapi.GetInvitationResponseObject, error) {
	return nil, nil //nolint:nilnil
}

func (s *strictSrv) RevokeInvitation(_ context.Context, _ httpapi.RevokeInvitationRequestObject) (httpapi.RevokeInvitationResponseObject, error) {
	return nil, nil //nolint:nilnil
}

func (s *strictSrv) AcceptInvitation(_ context.Context, _ httpapi.AcceptInvitationRequestObject) (httpapi.AcceptInvitationResponseObject, error) {
	return nil, nil //nolint:nilnil
}

// noopIdentityProvider satisfies identity.IdentityProvider without doing any
// work. Used to fulfil the strict interface in the tenancy security suite —
// every method either returns "" / nil or an error that surfaces as a 5xx
// problem (the tenancy tests never call into /v1/users).
type noopIdentityProvider struct{}

func (noopIdentityProvider) CreateUser(_ context.Context, _ string, _ identity.User) (string, error) {
	return "", nil
}

func (noopIdentityProvider) UpdateUser(_ context.Context, _, _, _, _ string) error { return nil }
func (noopIdentityProvider) SetEnabled(_ context.Context, _, _ string, _ bool) error {
	return nil
}

func (noopIdentityProvider) TriggerPasswordReset(_ context.Context, _, _ string) error { return nil }

func (noopIdentityProvider) TriggerEmailVerify(_ context.Context, _, _ string) error { return nil }

func (noopIdentityProvider) DeleteUser(_ context.Context, _, _ string) error { return nil }

func (noopIdentityProvider) StartSocialLogin(_ context.Context, _ identity.StartSocialLoginArgs) (string, error) {
	return "", nil
}

func (noopIdentityProvider) ListIdentityProviderLinks(_ context.Context, _, _ string) ([]identity.Provider, error) {
	return nil, nil
}

func (noopIdentityProvider) UnlinkIdentityProvider(_ context.Context, _, _ string, _ identity.Provider) error {
	return nil
}

// noopEvents is a no-op EventPublisher for the tenancy security tests. The
// suite never asserts on outbox events for the identity slice.
type noopEvents struct{}

func (noopEvents) Publish(_ context.Context, _, _ string, _ map[string]any) error { return nil }

// buildServer wires the same chi router the data plane binary uses, with the
// mock auth middleware. Idempotency middleware is intentionally omitted —
// the §17.3 matrix tests authentication / authorisation only.
//
// The identity slice is wired through a minimal in-memory test stack so the
// strict interface is fully satisfied without the tenancy suite needing
// per-test Keycloak / Postgres fixtures.
func buildServer(t *testing.T, prodEnv bool) (*httptest.Server, *fakeRepo) {
	t.Helper()
	if prodEnv {
		t.Setenv("SAAS_ENV", "prod")
	} else {
		t.Setenv("SAAS_ENV", "dev")
	}
	repo := newFakeRepo()
	svc := tenancy.NewService(repo, &captureEvents{})
	h := tenancy.NewHandler(svc)

	idSvc := identity.NewService(identity.Config{
		Repo:         newTenancySuiteIdentityRepo(),
		Provider:     noopIdentityProvider{},
		Hasher:       identity.NewStaticEmailHasher(nil),
		Events:       noopEvents{},
		DeploymentID: "dep_test",
	})
	idH := identity.NewHandler(idSvc)

	// Phase 6: stub notifications handler so the strict-server interface
	// is fully satisfied. The tenancy suite never calls /v1/notifications;
	// the stub repo returns ErrNotFound for any lookup.
	notifSvc := notifications.NewService(notifications.Config{
		Repo:         newTenancySuiteNotificationsRepo(),
		Events:       noopEvents{},
		DeploymentID: "dep_test",
	})
	notifH := notifications.NewHandler(notifSvc)

	r := chi.NewRouter()
	r.Use(auth.MockMiddleware)
	httpapi.HandlerFromMux(httpapi.NewStrictHandler(&strictSrv{tenants: h, identity: idH, notifications: notifH}, nil), r)
	return httptest.NewServer(r), repo
}

// seedTenant inserts a tenant directly into the fake repo so authorisation
// tests have a target with a well-known id.
func seedTenant(repo *fakeRepo, id, slug string) {
	t := tenancy.Tenant{
		ID:     id,
		Slug:   slug,
		Name:   "fixture",
		Status: tenancy.StatusActive,
		RowSeq: 1,
	}
	repo.tenants[id] = t
	repo.bySlug[slug] = id
}

// TestTenants_AuthZ_SameTenantAllowed — case 1 of the §17.3 matrix.
func TestTenants_AuthZ_SameTenantAllowed(t *testing.T) {
	srv, repo := buildServer(t, false)
	defer srv.Close()
	tenantID := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	seedTenant(repo, tenantID, "acme")

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+tenantID, nil)
	req.Header.Set("X-Mock-Tenant-Id", tenantID)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	if etag := resp.Header.Get("ETag"); !strings.HasPrefix(etag, `W/"v`) {
		t.Fatalf("expected weak ETag, got %q", etag)
	}
}

// TestTenants_AuthZ_CrossTenantDenied — case 2: caller A tries to read
// tenant B and receives 403 forbidden.
func TestTenants_AuthZ_CrossTenantDenied(t *testing.T) {
	srv, repo := buildServer(t, false)
	defer srv.Close()
	a := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	b := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"
	seedTenant(repo, a, "acme")
	seedTenant(repo, b, "globex")

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+b, nil)
	req.Header.Set("X-Mock-Tenant-Id", a)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", resp.StatusCode)
	}
}

// TestTenants_AuthZ_MissingContext — case 3: no mock header → 401 unauthorized.
func TestTenants_AuthZ_MissingContext(t *testing.T) {
	srv, repo := buildServer(t, false)
	defer srv.Close()
	id := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	seedTenant(repo, id, "acme")

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+id, nil)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", resp.StatusCode)
	}
}

// TestTenants_AuthZ_MockHeaderRefusedInProd — case 4: production builds
// reject the mock header outright.
func TestTenants_AuthZ_MockHeaderRefusedInProd(t *testing.T) {
	srv, repo := buildServer(t, true)
	defer srv.Close()
	id := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	seedTenant(repo, id, "acme")

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+id, nil)
	req.Header.Set("X-Mock-Tenant-Id", id)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401 in prod, got %d", resp.StatusCode)
	}
}

// TestTenants_AuthZ_XTenantIdHeaderIgnored — case 5: the spec forbids the
// `X-Tenant-Id` header; setting it must NOT authenticate the caller.
func TestTenants_AuthZ_XTenantIdHeaderIgnored(t *testing.T) {
	srv, repo := buildServer(t, false)
	defer srv.Close()
	id := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	seedTenant(repo, id, "acme")

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+id, nil)
	// Deliberately set X-Tenant-Id (banned header). The mock middleware must
	// ignore it — only X-Mock-Tenant-Id is honoured in dev.
	req.Header.Set("X-Tenant-Id", id)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401 (header ignored), got %d", resp.StatusCode)
	}
}

// TestTenants_AuthZ_ActingTenantWithoutScope — case 6: X-Acting-Tenant-Id
// without the operator-impersonation scope must not promote the caller.
// Phase 2 does not implement scopes yet, so the only enforcement that
// matters is: setting the header alone is NOT sufficient to access another
// tenant's resource.
func TestTenants_AuthZ_ActingTenantWithoutScope(t *testing.T) {
	srv, repo := buildServer(t, false)
	defer srv.Close()
	a := "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"
	b := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"
	seedTenant(repo, a, "acme")
	seedTenant(repo, b, "globex")

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/v1/tenants/"+b, nil)
	req.Header.Set("X-Mock-Tenant-Id", a)
	req.Header.Set("X-Acting-Tenant-Id", b)
	resp, err := srv.Client().Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("expected 403 (acting-tenant ignored without scope), got %d", resp.StatusCode)
	}
}

// ---------------------------------------------------------------------------
// In-memory identity repo for the tenancy suite. The §17.3 matrix tests on
// the tenancy slice never call into /v1/users, but the strict server
// interface needs a real handler to be wired. This in-memory repo lets the
// identity handler exist without dragging Postgres into the tenancy tests.
// ---------------------------------------------------------------------------

type tenancySuiteIdentityRepo struct{}

func newTenancySuiteIdentityRepo() *tenancySuiteIdentityRepo { return &tenancySuiteIdentityRepo{} }

func (*tenancySuiteIdentityRepo) Create(context.Context, identity.User) (identity.User, error) {
	return identity.User{}, identity.ErrNotFound
}

func (*tenancySuiteIdentityRepo) Get(context.Context, string, string) (identity.User, error) {
	return identity.User{}, identity.ErrNotFound
}

func (*tenancySuiteIdentityRepo) GetByEmailHash(context.Context, string, []byte) (identity.User, error) {
	return identity.User{}, identity.ErrNotFound
}

func (*tenancySuiteIdentityRepo) List(context.Context, string, int, *identity.ListCursor, []byte) ([]identity.User, bool, error) {
	return nil, false, nil
}

func (*tenancySuiteIdentityRepo) Update(context.Context, string, string, int64, identity.UpdatePatch) (identity.User, error) {
	return identity.User{}, identity.ErrNotFound
}

func (*tenancySuiteIdentityRepo) SetStatus(context.Context, string, string, identity.Status) (identity.User, error) {
	return identity.User{}, identity.ErrNotFound
}

func (*tenancySuiteIdentityRepo) SetEmailVerified(context.Context, string, string, bool) (identity.User, error) {
	return identity.User{}, identity.ErrNotFound
}

func (*tenancySuiteIdentityRepo) SoftDelete(context.Context, string, string, int64) (identity.User, error) {
	return identity.User{}, identity.ErrNotFound
}

func (*tenancySuiteIdentityRepo) LinkSocialProvider(context.Context, string, string, identity.Provider, string) error {
	return nil
}

func (*tenancySuiteIdentityRepo) UnlinkSocialProvider(context.Context, string, string, identity.Provider) error {
	return nil
}

func (*tenancySuiteIdentityRepo) ListSocialProviders(context.Context, string, string) ([]identity.SocialProvider, error) {
	return nil, nil
}

func (*tenancySuiteIdentityRepo) InsertSocialLoginState(context.Context, identity.SocialLoginState) error {
	return nil
}

func (*tenancySuiteIdentityRepo) ConsumeSocialLoginState(context.Context, string) (identity.SocialLoginState, error) {
	return identity.SocialLoginState{}, identity.ErrNotFound
}

// ---------------------------------------------------------------------------
// notifications stub repo — same pattern; every read returns ErrNotFound,
// every write is a no-op. The tenancy §17.3 matrix never exercises
// /v1/notifications, so a stub is sufficient.
// ---------------------------------------------------------------------------

type tenancySuiteNotificationsRepo struct{}

func newTenancySuiteNotificationsRepo() *tenancySuiteNotificationsRepo {
	return &tenancySuiteNotificationsRepo{}
}

func (*tenancySuiteNotificationsRepo) CreateChannel(context.Context, notifications.Channel) (notifications.Channel, error) {
	return notifications.Channel{}, notifications.ErrInvalidInput
}

func (*tenancySuiteNotificationsRepo) GetChannel(context.Context, string, string) (notifications.Channel, error) {
	return notifications.Channel{}, notifications.ErrNotFound
}

func (*tenancySuiteNotificationsRepo) GetChannelByName(context.Context, string, string) (notifications.Channel, error) {
	return notifications.Channel{}, notifications.ErrNotFound
}

func (*tenancySuiteNotificationsRepo) ListChannels(context.Context, string, int) ([]notifications.Channel, error) {
	return nil, nil
}

func (*tenancySuiteNotificationsRepo) UpdateChannel(context.Context, string, string, int64, notifications.ChannelPatch) (notifications.Channel, error) {
	return notifications.Channel{}, notifications.ErrNotFound
}

func (*tenancySuiteNotificationsRepo) DeleteChannel(context.Context, string, string, int64) error {
	return notifications.ErrNotFound
}

func (*tenancySuiteNotificationsRepo) RotateChannelSecrets(context.Context, string, string, string) (notifications.Channel, error) {
	return notifications.Channel{}, notifications.ErrNotFound
}

func (*tenancySuiteNotificationsRepo) SetChannelNovuIntegrationID(context.Context, string, string) error {
	return nil
}

func (*tenancySuiteNotificationsRepo) RegisterWorkflow(context.Context, notifications.Workflow) (notifications.Workflow, error) {
	return notifications.Workflow{}, notifications.ErrInvalidInput
}

func (*tenancySuiteNotificationsRepo) GetWorkflowByName(context.Context, string, string) (notifications.Workflow, error) {
	return notifications.Workflow{}, notifications.ErrNotFound
}

func (*tenancySuiteNotificationsRepo) ListWorkflows(context.Context, string) ([]notifications.Workflow, error) {
	return nil, nil
}

func (*tenancySuiteNotificationsRepo) UpdateWorkflow(context.Context, string, string, notifications.WorkflowPatch) (notifications.Workflow, error) {
	return notifications.Workflow{}, notifications.ErrNotFound
}

func (*tenancySuiteNotificationsRepo) CreateNotification(context.Context, notifications.Notification) (notifications.Notification, error) {
	return notifications.Notification{}, notifications.ErrInvalidInput
}

func (*tenancySuiteNotificationsRepo) GetNotification(context.Context, string, string) (notifications.Notification, error) {
	return notifications.Notification{}, notifications.ErrNotFound
}

func (*tenancySuiteNotificationsRepo) ListNotifications(context.Context, string, int, *notifications.ListCursor) ([]notifications.Notification, bool, error) {
	return nil, false, nil
}

func (*tenancySuiteNotificationsRepo) UpdateNotificationStatus(context.Context, string, notifications.NotificationStatus, *string, *string) (notifications.Notification, error) {
	return notifications.Notification{}, notifications.ErrNotFound
}
