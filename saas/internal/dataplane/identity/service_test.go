package identity_test

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/omarss/saas/internal/dataplane/identity"
	"github.com/omarss/saas/internal/platform/auth"
)

// --- test doubles ---------------------------------------------------------

// fakeRepo is an in-memory Repository used by service unit tests. It does
// not emulate RLS — RLS is covered by repo_pgx_test.go.
type fakeRepo struct {
	mu        sync.Mutex
	users     map[string]identity.User
	byHash    map[string]string // hex(hash) -> userID
	states    map[string]identity.SocialLoginState
	links     map[string][]identity.SocialProvider // userID -> providers
	createErr error
}

func newFakeRepo() *fakeRepo {
	return &fakeRepo{
		users:  map[string]identity.User{},
		byHash: map[string]string{},
		states: map[string]identity.SocialLoginState{},
		links:  map[string][]identity.SocialProvider{},
	}
}

func (r *fakeRepo) Create(_ context.Context, u identity.User) (identity.User, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.createErr != nil {
		return identity.User{}, r.createErr
	}
	key := string(u.EmailLookupHash)
	if existing, ok := r.byHash[key]; ok {
		if r.users[existing].TenantID == u.TenantID {
			return identity.User{}, identity.ErrEmailTaken
		}
	}
	r.users[u.ID] = u
	r.byHash[key] = u.ID
	return u, nil
}

func (r *fakeRepo) Get(_ context.Context, tenantID, userID string) (identity.User, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	u, ok := r.users[userID]
	if !ok || u.DeletedAt != nil || u.TenantID != tenantID {
		return identity.User{}, identity.ErrNotFound
	}
	return u, nil
}

func (r *fakeRepo) GetByEmailHash(_ context.Context, tenantID string, hash []byte) (identity.User, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	id, ok := r.byHash[string(hash)]
	if !ok {
		return identity.User{}, identity.ErrNotFound
	}
	u := r.users[id]
	if u.TenantID != tenantID || u.DeletedAt != nil {
		return identity.User{}, identity.ErrNotFound
	}
	return u, nil
}

func (r *fakeRepo) List(_ context.Context, tenantID string, _ int, _ *identity.ListCursor, _ []byte) ([]identity.User, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]identity.User, 0)
	for _, u := range r.users {
		if u.TenantID == tenantID && u.DeletedAt == nil {
			out = append(out, u)
		}
	}
	return out, false, nil
}

func (r *fakeRepo) Update(_ context.Context, tenantID, userID string, expectedSeq int64, patch identity.UpdatePatch) (identity.User, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	u, ok := r.users[userID]
	if !ok || u.TenantID != tenantID || u.DeletedAt != nil {
		return identity.User{}, identity.ErrNotFound
	}
	if u.RowSeq != expectedSeq {
		return identity.User{}, identity.ErrETagMismatch
	}
	if patch.Name != nil {
		u.Name = *patch.Name
	}
	if patch.Phone != nil {
		u.Phone = *patch.Phone
	}
	if patch.PatchMetadata {
		u.Metadata = patch.Metadata
	}
	u.RowSeq++
	u.UpdatedAt = time.Now().UTC()
	r.users[userID] = u
	return u, nil
}

func (r *fakeRepo) SetStatus(_ context.Context, tenantID, userID string, st identity.Status) (identity.User, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	u, ok := r.users[userID]
	if !ok || u.TenantID != tenantID {
		return identity.User{}, identity.ErrNotFound
	}
	u.Status = st
	u.RowSeq++
	r.users[userID] = u
	return u, nil
}

func (r *fakeRepo) SetEmailVerified(_ context.Context, tenantID, userID string, verified bool) (identity.User, error) {
	return r.SetStatus(context.Background(), tenantID, userID, identity.StatusActive) // simplified for tests
}

func (r *fakeRepo) SoftDelete(_ context.Context, tenantID, userID string, _ int64) (identity.User, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	u, ok := r.users[userID]
	if !ok || u.TenantID != tenantID {
		return identity.User{}, identity.ErrNotFound
	}
	now := time.Now().UTC()
	u.Status = identity.StatusDeleted
	u.DeletedAt = &now
	u.RowSeq++
	r.users[userID] = u
	return u, nil
}

func (r *fakeRepo) LinkSocialProvider(_ context.Context, _, userID string, p identity.Provider, sub string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.links[userID] = append(r.links[userID], identity.SocialProvider{Provider: p, ExternalSubject: sub, LinkedAt: time.Now()})
	return nil
}

func (r *fakeRepo) UnlinkSocialProvider(_ context.Context, _, userID string, p identity.Provider) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := r.links[userID][:0]
	for _, sp := range r.links[userID] {
		if sp.Provider != p {
			out = append(out, sp)
		}
	}
	r.links[userID] = out
	return nil
}

func (r *fakeRepo) ListSocialProviders(_ context.Context, _, userID string) ([]identity.SocialProvider, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]identity.SocialProvider{}, r.links[userID]...), nil
}

func (r *fakeRepo) InsertSocialLoginState(_ context.Context, s identity.SocialLoginState) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.states[s.State] = s
	return nil
}

func (r *fakeRepo) ConsumeSocialLoginState(_ context.Context, token string) (identity.SocialLoginState, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	s, ok := r.states[token]
	if !ok {
		return identity.SocialLoginState{}, identity.ErrNotFound
	}
	now := time.Now().UTC()
	s.ConsumedAt = &now
	r.states[token] = s
	return s, nil
}

// fakeProvider is an in-memory IdentityProvider with a few hooks for failure
// injection. It captures every call for assertion.
type fakeProvider struct {
	createCalls    int
	createErr      error
	deleteCalls    []string
	setEnabledMap  map[string]bool
	passwordResets []string
	emailVerifies  []string
	links          map[string][]identity.Provider
}

func newFakeProvider() *fakeProvider {
	return &fakeProvider{
		setEnabledMap: map[string]bool{},
		links:         map[string][]identity.Provider{},
	}
}

func (f *fakeProvider) CreateUser(_ context.Context, _ string, u identity.User) (string, error) {
	if f.createErr != nil {
		return "", f.createErr
	}
	f.createCalls++
	return "kc_" + u.ID, nil
}

func (f *fakeProvider) UpdateUser(_ context.Context, _, _, _, _ string) error { return nil }
func (f *fakeProvider) SetEnabled(_ context.Context, _, kcID string, enabled bool) error {
	f.setEnabledMap[kcID] = enabled
	return nil
}

func (f *fakeProvider) TriggerPasswordReset(_ context.Context, _, kcID string) error {
	f.passwordResets = append(f.passwordResets, kcID)
	return nil
}

func (f *fakeProvider) TriggerEmailVerify(_ context.Context, _, kcID string) error {
	f.emailVerifies = append(f.emailVerifies, kcID)
	return nil
}

func (f *fakeProvider) DeleteUser(_ context.Context, _, kcID string) error {
	f.deleteCalls = append(f.deleteCalls, kcID)
	return nil
}

func (f *fakeProvider) StartSocialLogin(_ context.Context, args identity.StartSocialLoginArgs) (string, error) {
	if !args.Provider.Valid() || args.Nonce == "" {
		return "", errors.New("invalid")
	}
	return "https://kc.example.com/realms/" + args.Realm + "/broker/" + string(args.Provider) + "/link?nonce=" + args.Nonce, nil
}

func (f *fakeProvider) ListIdentityProviderLinks(_ context.Context, _, kcID string) ([]identity.Provider, error) {
	return f.links[kcID], nil
}

func (f *fakeProvider) UnlinkIdentityProvider(_ context.Context, _, kcID string, p identity.Provider) error {
	out := f.links[kcID][:0]
	for _, ex := range f.links[kcID] {
		if ex != p {
			out = append(out, ex)
		}
	}
	f.links[kcID] = out
	return nil
}

// capturedEvents records publish calls so tests can assert event emission.
type capturedEvents struct {
	mu     sync.Mutex
	events []struct {
		eventType string
		tenantID  string
	}
}

func (c *capturedEvents) Publish(_ context.Context, eventType, tenantID string, _ map[string]any) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.events = append(c.events, struct {
		eventType string
		tenantID  string
	}{eventType, tenantID})
	return nil
}

func (c *capturedEvents) has(eventType string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	for _, e := range c.events {
		if e.eventType == eventType {
			return true
		}
	}
	return false
}

// --- helpers --------------------------------------------------------------

const fixtureTenant = "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"

func newService(t *testing.T) (*identity.Service, *fakeRepo, *fakeProvider, *capturedEvents) {
	t.Helper()
	repo := newFakeRepo()
	prov := newFakeProvider()
	events := &capturedEvents{}
	svc := identity.NewService(identity.Config{
		Repo:         repo,
		Provider:     prov,
		Hasher:       identity.NewStaticEmailHasher(nil),
		Events:       events,
		DeploymentID: "dep_test",
		Realm:        "saas-data-test",
		ClientID:     "saas-data-test",
	})
	return svc, repo, prov, events
}

// withTenant returns a context already bound to fixtureTenant — saves
// boilerplate across the §17.3 matrix.
func withTenant(tenantID string) context.Context {
	return auth.ContextWithTenant(context.Background(), tenantID)
}

// --- service tests --------------------------------------------------------

func TestService_Create_HappyPath(t *testing.T) {
	svc, repo, prov, events := newService(t)
	ctx := withTenant(fixtureTenant)

	got, err := svc.Create(ctx, fixtureTenant, "alice@example.com", "Alice", true, nil)
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	if !strings.HasPrefix(got.ID, "user_") {
		t.Errorf("id prefix wrong: %q", got.ID)
	}
	if got.KeycloakUserID == "" {
		t.Errorf("KC user id missing")
	}
	if got.Status != identity.StatusActive {
		t.Errorf("status: got %q want active", got.Status)
	}
	if prov.createCalls != 1 {
		t.Errorf("expected 1 KC create call, got %d", prov.createCalls)
	}
	if len(prov.emailVerifies) != 1 {
		t.Errorf("expected verify-email trigger, got %d", len(prov.emailVerifies))
	}
	if !events.has("user.created") {
		t.Errorf("missing user.created event")
	}
	if _, ok := repo.users[got.ID]; !ok {
		t.Errorf("user not persisted")
	}
}

func TestService_Create_DuplicateEmailInSameTenant(t *testing.T) {
	svc, _, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)
	if _, err := svc.Create(ctx, fixtureTenant, "bob@example.com", "Bob", false, nil); err != nil {
		t.Fatalf("first create: %v", err)
	}
	_, err := svc.Create(ctx, fixtureTenant, "bob@example.com", "Bob 2", false, nil)
	if !errors.Is(err, identity.ErrEmailTaken) {
		t.Fatalf("expected ErrEmailTaken, got %v", err)
	}
}

func TestService_Create_KCFailureRollsBackDBInsert(t *testing.T) {
	svc, repo, prov, _ := newService(t)
	prov.createErr = errors.New("keycloak down")
	ctx := withTenant(fixtureTenant)

	_, err := svc.Create(ctx, fixtureTenant, "carol@example.com", "Carol", false, nil)
	if err == nil {
		t.Fatalf("expected error when KC fails")
	}
	if len(repo.users) != 0 {
		t.Errorf("DB row persisted despite KC failure: %d", len(repo.users))
	}
}

func TestService_Create_InvalidEmail(t *testing.T) {
	svc, _, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)
	cases := []string{"", "not-an-email", "@example.com", "x@y", strings.Repeat("a", 300) + "@e.com"}
	for _, em := range cases {
		if _, err := svc.Create(ctx, fixtureTenant, em, "x", false, nil); !errors.Is(err, identity.ErrInvalidInput) {
			t.Errorf("email %q: expected ErrInvalidInput, got %v", em, err)
		}
	}
}

func TestService_Disable_FlipsStatusAndKC(t *testing.T) {
	svc, _, prov, events := newService(t)
	ctx := withTenant(fixtureTenant)
	created, err := svc.Create(ctx, fixtureTenant, "dan@example.com", "Dan", false, nil)
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	got, err := svc.Disable(ctx, fixtureTenant, created.ID)
	if err != nil {
		t.Fatalf("Disable: %v", err)
	}
	if got.Status != identity.StatusDisabled {
		t.Errorf("expected disabled status, got %q", got.Status)
	}
	if prov.setEnabledMap[created.KeycloakUserID] {
		t.Errorf("KC not set to disabled")
	}
	if !events.has("user.disabled") {
		t.Errorf("missing user.disabled event")
	}
}

func TestService_ResetPassword_TriggersExecuteActions(t *testing.T) {
	svc, _, prov, _ := newService(t)
	ctx := withTenant(fixtureTenant)
	u, err := svc.Create(ctx, fixtureTenant, "eve@example.com", "Eve", false, nil)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := svc.TriggerPasswordReset(ctx, fixtureTenant, u.ID); err != nil {
		t.Fatalf("TriggerPasswordReset: %v", err)
	}
	if len(prov.passwordResets) != 1 || prov.passwordResets[0] != u.KeycloakUserID {
		t.Errorf("unexpected reset calls: %v", prov.passwordResets)
	}
}

func TestService_ResetPassword_DisabledUserRejected(t *testing.T) {
	svc, _, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)
	u, _ := svc.Create(ctx, fixtureTenant, "frank@example.com", "Frank", false, nil)
	_, _ = svc.Disable(ctx, fixtureTenant, u.ID)

	err := svc.TriggerPasswordReset(ctx, fixtureTenant, u.ID)
	if !errors.Is(err, identity.ErrUserDisabled) {
		t.Errorf("expected ErrUserDisabled, got %v", err)
	}
}

func TestService_StartSocialLogin_HappyPath(t *testing.T) {
	svc, _, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)
	u, err := svc.Create(ctx, fixtureTenant, "gina@example.com", "Gina", false, nil)
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	res, err := svc.StartSocialLogin(ctx, fixtureTenant, u.ID, identity.ProviderGoogle, "https://app/cb", "ss", "issued-for")
	if err != nil {
		t.Fatalf("StartSocialLogin: %v", err)
	}
	if res.AuthorizationURL == "" || res.State == "" {
		t.Errorf("missing fields: %+v", res)
	}
}

func TestService_StartSocialLogin_InvalidProvider(t *testing.T) {
	svc, _, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)
	u, _ := svc.Create(ctx, fixtureTenant, "hank@example.com", "Hank", false, nil)

	_, err := svc.StartSocialLogin(ctx, fixtureTenant, u.ID, identity.Provider("microsoft"), "https://app/cb", "ss", "if")
	if !errors.Is(err, identity.ErrInvalidProvider) {
		t.Errorf("expected ErrInvalidProvider, got %v", err)
	}
}

func TestService_StartSocialLogin_DisabledUserRejected(t *testing.T) {
	svc, _, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)
	u, _ := svc.Create(ctx, fixtureTenant, "ivy@example.com", "Ivy", false, nil)
	_, _ = svc.Disable(ctx, fixtureTenant, u.ID)

	_, err := svc.StartSocialLogin(ctx, fixtureTenant, u.ID, identity.ProviderGoogle, "https://app/cb", "ss", "if")
	if !errors.Is(err, identity.ErrUserDisabled) {
		t.Errorf("expected ErrUserDisabled, got %v", err)
	}
}

func TestService_StartSocialLogin_CrossTenantRejected(t *testing.T) {
	svc, _, _, _ := newService(t)
	otherTenant := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"

	// Create user as tenant_A.
	ctxA := withTenant(fixtureTenant)
	uA, err := svc.Create(ctxA, fixtureTenant, "jane@example.com", "Jane", false, nil)
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	// Cross-tenant attack: ctxB tries to link a social provider to uA.
	ctxB := withTenant(otherTenant)
	_, err = svc.StartSocialLogin(ctxB, fixtureTenant, uA.ID, identity.ProviderGoogle, "https://app/cb", "ss", "if")
	if !errors.Is(err, auth.ErrCrossTenant) {
		t.Errorf("expected cross-tenant denial, got %v", err)
	}
}

func TestService_Get_CrossTenant_Forbidden(t *testing.T) {
	svc, _, _, _ := newService(t)
	otherTenant := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"

	ctxA := withTenant(fixtureTenant)
	uA, _ := svc.Create(ctxA, fixtureTenant, "kate@example.com", "Kate", false, nil)

	ctxB := withTenant(otherTenant)
	if _, err := svc.Get(ctxB, fixtureTenant, uA.ID); !errors.Is(err, auth.ErrCrossTenant) {
		t.Errorf("expected ErrCrossTenant, got %v", err)
	}
}

func TestService_Get_MissingContext_Unauthorized(t *testing.T) {
	svc, _, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)
	u, _ := svc.Create(ctx, fixtureTenant, "leo@example.com", "Leo", false, nil)

	if _, err := svc.Get(context.Background(), fixtureTenant, u.ID); !errors.Is(err, auth.ErrUnauthorized) {
		t.Errorf("expected ErrUnauthorized, got %v", err)
	}
}
