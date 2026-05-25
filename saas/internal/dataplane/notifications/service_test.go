package notifications_test

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/omarss/saas/internal/dataplane/notifications"
	"github.com/omarss/saas/internal/platform/auth"
)

// --- test doubles ---------------------------------------------------------

// fakeRepo is an in-memory Repository used by service unit tests. It does
// not emulate RLS — RLS is covered by repo_pgx_test.go (integration).
type fakeRepo struct {
	mu         sync.Mutex
	channels   map[string]notifications.Channel
	byName     map[string]string // tenantID|name -> channelID
	workflows  map[string]notifications.Workflow
	wfByName   map[string]string // tenantID|name -> workflowID
	notifs     map[string]notifications.Notification
	createCErr error
	createNErr error
}

func newFakeRepo() *fakeRepo {
	return &fakeRepo{
		channels:  map[string]notifications.Channel{},
		byName:    map[string]string{},
		workflows: map[string]notifications.Workflow{},
		wfByName:  map[string]string{},
		notifs:    map[string]notifications.Notification{},
	}
}

func chanKey(tenant, name string) string { return tenant + "|" + name }

func (r *fakeRepo) CreateChannel(_ context.Context, c notifications.Channel) (notifications.Channel, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.createCErr != nil {
		return notifications.Channel{}, r.createCErr
	}
	k := chanKey(c.TenantID, c.Name)
	if _, ok := r.byName[k]; ok {
		return notifications.Channel{}, notifications.ErrNameTaken
	}
	// Mirror the repo behaviour: the plaintext gets cleared after the walker.
	c.Secrets = ""
	r.channels[c.ID] = c
	r.byName[k] = c.ID
	return c, nil
}

func (r *fakeRepo) GetChannel(_ context.Context, tenant, id string) (notifications.Channel, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	c, ok := r.channels[id]
	if !ok || c.TenantID != tenant || c.DeletedAt != nil {
		return notifications.Channel{}, notifications.ErrNotFound
	}
	return c, nil
}

func (r *fakeRepo) GetChannelByName(_ context.Context, tenant, name string) (notifications.Channel, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	id, ok := r.byName[chanKey(tenant, name)]
	if !ok {
		return notifications.Channel{}, notifications.ErrNotFound
	}
	return r.channels[id], nil
}

func (r *fakeRepo) ListChannels(_ context.Context, tenant string, _ int) ([]notifications.Channel, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]notifications.Channel, 0)
	for _, c := range r.channels {
		if c.TenantID == tenant && c.DeletedAt == nil {
			out = append(out, c)
		}
	}
	return out, nil
}

func (r *fakeRepo) UpdateChannel(_ context.Context, tenant, id string, seq int64, patch notifications.ChannelPatch) (notifications.Channel, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	c, ok := r.channels[id]
	if !ok || c.TenantID != tenant || c.DeletedAt != nil {
		return notifications.Channel{}, notifications.ErrNotFound
	}
	if c.RowSeq != seq {
		return notifications.Channel{}, notifications.ErrETagMismatch
	}
	if patch.Name != nil {
		c.Name = *patch.Name
	}
	if patch.Status != nil {
		c.Status = *patch.Status
	}
	if patch.PatchDefaults {
		c.IsDefaultFor = patch.IsDefaultFor
	}
	if patch.PatchConfig {
		c.Config = patch.Config
	}
	c.RowSeq++
	r.channels[id] = c
	return c, nil
}

func (r *fakeRepo) DeleteChannel(_ context.Context, tenant, id string, seq int64) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	c, ok := r.channels[id]
	if !ok || c.TenantID != tenant {
		return notifications.ErrNotFound
	}
	if c.RowSeq != seq {
		return notifications.ErrETagMismatch
	}
	now := time.Now()
	c.DeletedAt = &now
	r.channels[id] = c
	return nil
}

func (r *fakeRepo) RotateChannelSecrets(_ context.Context, tenant, id, _ string) (notifications.Channel, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	c, ok := r.channels[id]
	if !ok || c.TenantID != tenant {
		return notifications.Channel{}, notifications.ErrNotFound
	}
	now := time.Now()
	c.LastRotatedAt = &now
	c.RowSeq++
	r.channels[id] = c
	return c, nil
}

func (r *fakeRepo) SetChannelNovuIntegrationID(_ context.Context, id, novuID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	c, ok := r.channels[id]
	if !ok {
		return notifications.ErrNotFound
	}
	c.NovuIntegrationID = &novuID
	r.channels[id] = c
	return nil
}

func (r *fakeRepo) RegisterWorkflow(_ context.Context, w notifications.Workflow) (notifications.Workflow, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	k := chanKey(w.TenantID, w.Name)
	if _, ok := r.wfByName[k]; ok {
		return notifications.Workflow{}, notifications.ErrNameTaken
	}
	r.workflows[w.ID] = w
	r.wfByName[k] = w.ID
	return w, nil
}

func (r *fakeRepo) GetWorkflowByName(_ context.Context, tenant, name string) (notifications.Workflow, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	id, ok := r.wfByName[chanKey(tenant, name)]
	if !ok {
		return notifications.Workflow{}, notifications.ErrNotFound
	}
	return r.workflows[id], nil
}

func (r *fakeRepo) UpdateWorkflow(_ context.Context, tenant, id string, patch notifications.WorkflowPatch) (notifications.Workflow, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	w, ok := r.workflows[id]
	if !ok || w.TenantID != tenant {
		return notifications.Workflow{}, notifications.ErrNotFound
	}
	if patch.NovuWorkflowID != nil {
		w.NovuWorkflowID = *patch.NovuWorkflowID
	}
	if patch.Description != nil {
		w.Description = *patch.Description
	}
	r.workflows[id] = w
	return w, nil
}

func (r *fakeRepo) ListWorkflows(_ context.Context, tenant string) ([]notifications.Workflow, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := []notifications.Workflow{}
	for _, w := range r.workflows {
		if w.TenantID == tenant {
			out = append(out, w)
		}
	}
	return out, nil
}

func (r *fakeRepo) CreateNotification(_ context.Context, n notifications.Notification) (notifications.Notification, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.createNErr != nil {
		return notifications.Notification{}, r.createNErr
	}
	// Mirror repo behaviour: the walker cleared Payload, persistent row
	// carries only the envelope.
	n.Payload = ""
	r.notifs[n.ID] = n
	return n, nil
}

func (r *fakeRepo) GetNotification(_ context.Context, tenant, id string) (notifications.Notification, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	n, ok := r.notifs[id]
	if !ok || n.TenantID != tenant {
		return notifications.Notification{}, notifications.ErrNotFound
	}
	return n, nil
}

func (r *fakeRepo) ListNotifications(_ context.Context, tenant string, _ int, _ *notifications.ListCursor) ([]notifications.Notification, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := []notifications.Notification{}
	for _, n := range r.notifs {
		if n.TenantID == tenant {
			out = append(out, n)
		}
	}
	return out, false, nil
}

func (r *fakeRepo) UpdateNotificationStatus(_ context.Context, id string, status notifications.NotificationStatus, reason *string, novuID *string) (notifications.Notification, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	n, ok := r.notifs[id]
	if !ok {
		return notifications.Notification{}, notifications.ErrNotFound
	}
	n.Status = status
	n.FailureReason = reason
	n.NovuTransactionID = novuID
	r.notifs[id] = n
	return n, nil
}

// capturedEvents records publish calls so tests can assert event emission.
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

// --- helpers --------------------------------------------------------------

const fixtureTenant = "tenant_01HAAAAAAAAAAAAAAAAAAAAAAA"

func newService(t *testing.T) (*notifications.Service, *fakeRepo, *capturedEvents) {
	t.Helper()
	repo := newFakeRepo()
	events := &capturedEvents{}
	svc := notifications.NewService(notifications.Config{
		Repo:         repo,
		Events:       events,
		DeploymentID: "dep_test",
	})
	return svc, repo, events
}

func withTenant(tenantID string) context.Context {
	return auth.ContextWithTenant(context.Background(), tenantID)
}

// --- service tests --------------------------------------------------------

func TestService_CreateChannel_SMTP_HappyPath(t *testing.T) {
	svc, repo, events := newService(t)
	ctx := withTenant(fixtureTenant)

	got, err := svc.CreateChannel(ctx, fixtureTenant, notifications.CreateChannelInput{
		Provider: notifications.ProviderSMTP,
		Name:     "primary",
		Config:   map[string]string{"host": "mailhog", "port": "1025", "from": "noreply@example.test"},
		Credentials: notifications.CredentialsBundle{
			SMTP: &notifications.SMTPCredentials{Username: "u", Password: "p"},
		},
	})
	if err != nil {
		t.Fatalf("CreateChannel: %v", err)
	}
	if !strings.HasPrefix(got.ID, "chan_") {
		t.Errorf("id prefix: %q", got.ID)
	}
	if got.Secrets != "" {
		t.Errorf("response leaks plaintext secrets: %q", got.Secrets)
	}
	if !events.has("notification_channel.created") {
		t.Errorf("missing channel.created event")
	}
	if _, ok := repo.channels[got.ID]; !ok {
		t.Errorf("channel not persisted")
	}
}

func TestService_CreateChannel_DuplicateName(t *testing.T) {
	svc, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)

	mk := func() error {
		_, err := svc.CreateChannel(ctx, fixtureTenant, notifications.CreateChannelInput{
			Provider:    notifications.ProviderSendGrid,
			Name:        "primary",
			Credentials: notifications.CredentialsBundle{SendGrid: &notifications.SendGridCredentials{APIKey: "sg-key"}},
		})
		return err
	}
	if err := mk(); err != nil {
		t.Fatalf("first create: %v", err)
	}
	if err := mk(); !errors.Is(err, notifications.ErrNameTaken) {
		t.Errorf("expected ErrNameTaken, got %v", err)
	}
}

func TestService_CreateChannel_BadCredsForProvider(t *testing.T) {
	svc, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)

	// SMTP provider but only SendGrid creds.
	_, err := svc.CreateChannel(ctx, fixtureTenant, notifications.CreateChannelInput{
		Provider:    notifications.ProviderSMTP,
		Name:        "x",
		Credentials: notifications.CredentialsBundle{SendGrid: &notifications.SendGridCredentials{APIKey: "y"}},
	})
	if !errors.Is(err, notifications.ErrInvalidCredentials) {
		t.Errorf("expected ErrInvalidCredentials, got %v", err)
	}
}

func TestService_CreateChannel_InvalidProvider(t *testing.T) {
	svc, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)
	_, err := svc.CreateChannel(ctx, fixtureTenant, notifications.CreateChannelInput{
		Provider: notifications.ChannelProvider("twilio"),
		Name:     "x",
	})
	if !errors.Is(err, notifications.ErrInvalidProvider) {
		t.Errorf("expected ErrInvalidProvider, got %v", err)
	}
}

func TestService_RotateCredentials_HappyPath(t *testing.T) {
	svc, _, events := newService(t)
	ctx := withTenant(fixtureTenant)

	ch, err := svc.CreateChannel(ctx, fixtureTenant, notifications.CreateChannelInput{
		Provider:    notifications.ProviderSendGrid,
		Name:        "rot",
		Credentials: notifications.CredentialsBundle{SendGrid: &notifications.SendGridCredentials{APIKey: "old"}},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	rot, err := svc.RotateChannelCredentials(ctx, fixtureTenant, ch.ID, notifications.CredentialsBundle{
		SendGrid: &notifications.SendGridCredentials{APIKey: "new"},
	})
	if err != nil {
		t.Fatalf("rotate: %v", err)
	}
	if rot.Secrets != "" {
		t.Errorf("rotation leaks plaintext secrets")
	}
	if rot.LastRotatedAt == nil {
		t.Errorf("expected LastRotatedAt to be set")
	}
	if !events.has("notification_channel.rotated") {
		t.Errorf("missing rotated event")
	}
}

func TestService_RotateCredentials_CrossTenantDenied(t *testing.T) {
	svc, _, _ := newService(t)
	otherTenant := "tenant_01HBBBBBBBBBBBBBBBBBBBBBBB"

	ctxA := withTenant(fixtureTenant)
	ch, _ := svc.CreateChannel(ctxA, fixtureTenant, notifications.CreateChannelInput{
		Provider:    notifications.ProviderSendGrid,
		Name:        "rot",
		Credentials: notifications.CredentialsBundle{SendGrid: &notifications.SendGridCredentials{APIKey: "k"}},
	})

	ctxB := withTenant(otherTenant)
	_, err := svc.RotateChannelCredentials(ctxB, fixtureTenant, ch.ID, notifications.CredentialsBundle{
		SendGrid: &notifications.SendGridCredentials{APIKey: "new"},
	})
	if !errors.Is(err, auth.ErrCrossTenant) {
		t.Errorf("expected ErrCrossTenant, got %v", err)
	}
}

func TestService_RegisterWorkflow_HappyPath(t *testing.T) {
	svc, _, events := newService(t)
	ctx := withTenant(fixtureTenant)

	wf, err := svc.RegisterWorkflow(ctx, fixtureTenant, notifications.RegisterWorkflowInput{
		Name:           "user.password_reset",
		NovuWorkflowID: "novu_wf_123",
		Description:    "Password reset email.",
	})
	if err != nil {
		t.Fatalf("RegisterWorkflow: %v", err)
	}
	if !strings.HasPrefix(wf.ID, "wf_") {
		t.Errorf("id prefix: %q", wf.ID)
	}
	if !events.has("notification_workflow.created") {
		t.Errorf("missing workflow.created event")
	}
}

func TestService_Send_HappyPath(t *testing.T) {
	svc, _, events := newService(t)
	ctx := withTenant(fixtureTenant)

	_, _ = svc.RegisterWorkflow(ctx, fixtureTenant, notifications.RegisterWorkflowInput{
		Name:           "user.password_reset",
		NovuWorkflowID: "novu_wf_123",
	})

	res, err := svc.Send(ctx, fixtureTenant, notifications.SendRequest{
		WorkflowName: "user.password_reset",
		ToUserID:     "user_01HAAAAAAAAAAAAAAAAAAAAAAA",
		Payload:      map[string]any{"reset_url": "https://app/r"},
	})
	if err != nil {
		t.Fatalf("Send: %v", err)
	}
	if !strings.HasPrefix(res.Notification.ID, "notif_") {
		t.Errorf("id prefix: %q", res.Notification.ID)
	}
	if res.Notification.Status != notifications.NotificationStatusQueued {
		t.Errorf("status: got %q want queued", res.Notification.Status)
	}
	if res.Notification.Payload != "" {
		t.Errorf("Send response leaks plaintext payload")
	}
	if !events.has("notification.queued") {
		t.Errorf("missing notification.queued event")
	}
}

func TestService_Send_UnknownWorkflow(t *testing.T) {
	svc, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)

	_, err := svc.Send(ctx, fixtureTenant, notifications.SendRequest{
		WorkflowName: "does-not-exist",
		ToUserID:     "user_01HAAAAAAAAAAAAAAAAAAAAAAA",
	})
	if !errors.Is(err, notifications.ErrWorkflowNotRegistered) {
		t.Errorf("expected ErrWorkflowNotRegistered, got %v", err)
	}
}

func TestService_GetChannel_NeverLeaksSecrets(t *testing.T) {
	svc, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)
	ch, err := svc.CreateChannel(ctx, fixtureTenant, notifications.CreateChannelInput{
		Provider:    notifications.ProviderSendGrid,
		Name:        "g",
		Credentials: notifications.CredentialsBundle{SendGrid: &notifications.SendGridCredentials{APIKey: "topsecret"}},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	got, err := svc.GetChannel(ctx, fixtureTenant, ch.ID)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.Secrets != "" {
		t.Errorf("GetChannel leaked secrets: %q", got.Secrets)
	}
}

// --- sync send path: ADR 013 outbox events ----------------------------------

// fakeNovu records the last TriggerWorkflow call and returns either a
// transaction id or an injected error. Implements notifications.NovuClient.
type fakeNovu struct {
	mu        sync.Mutex
	triggerID string
	triggerEr error
	called    int
}

func (f *fakeNovu) TriggerWorkflow(_ context.Context, _, _ string, _ map[string]any) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.called++
	return f.triggerID, f.triggerEr
}

func (f *fakeNovu) GetTransactionStatus(_ context.Context, _ string) (notifications.NotificationStatus, error) {
	return notifications.NotificationStatusSent, nil
}

func (f *fakeNovu) UpsertIntegration(_ context.Context, _ string, _ notifications.ChannelProvider, _ map[string]any) (string, error) {
	return "novu_int_xx", nil
}

func (f *fakeNovu) EnsureSubscriber(_ context.Context, _, _, _ string) error { return nil }

// fakeUserLookup returns a static UserInfo for any (tenant, user) so the
// sync send path's subscriber-attribute resolution is exercised.
type fakeUserLookup struct{}

func (fakeUserLookup) LookupUser(_ context.Context, _, userID string) (notifications.UserInfo, error) {
	return notifications.UserInfo{UserID: userID, Email: "redacted-by-test@example.com", Name: "Test User"}, nil
}

func newServiceWithNovu(t *testing.T, novu *fakeNovu) (*notifications.Service, *capturedEvents) {
	t.Helper()
	repo := newFakeRepo()
	events := &capturedEvents{}
	svc := notifications.NewService(notifications.Config{
		Repo:         repo,
		Events:       events,
		Novu:         novu,
		Users:        fakeUserLookup{},
		DeploymentID: "dep_test",
	})
	return svc, events
}

func TestSend_NovuSuccess_EmitsSent(t *testing.T) {
	novu := &fakeNovu{triggerID: "novu_tx_AAA"}
	svc, events := newServiceWithNovu(t, novu)
	ctx := withTenant(fixtureTenant)
	if _, err := svc.RegisterWorkflow(ctx, fixtureTenant, notifications.RegisterWorkflowInput{
		Name: "user.password_reset", NovuWorkflowID: "novu_wf_X",
	}); err != nil {
		t.Fatalf("register: %v", err)
	}
	res, err := svc.Send(ctx, fixtureTenant, notifications.SendRequest{
		WorkflowName: "user.password_reset",
		ToUserID:     "user_01HAAAAAAAAAAAAAAAAAAAAAAA",
		Payload:      map[string]any{"reset_url": "https://app/r"},
	})
	if err != nil {
		t.Fatalf("Send: %v", err)
	}
	// Outbox: queued THEN sent (delivery_failed must NOT appear).
	if !events.has("notification.queued") {
		t.Errorf("missing notification.queued")
	}
	if !events.has("notification.sent") {
		t.Errorf("missing notification.sent (sync trigger should fire it)")
	}
	if events.has("notification.delivery_failed") {
		t.Errorf("delivery_failed must not fire on success")
	}
	if res.Notification.Status != notifications.NotificationStatusSent {
		t.Errorf("status: got %q want sent", res.Notification.Status)
	}
	if novu.called != 1 {
		t.Errorf("novu trigger call count: got %d want 1", novu.called)
	}
}

func TestSend_NovuFailure_EmitsDeliveryFailed(t *testing.T) {
	novu := &fakeNovu{triggerEr: errors.New("novu 503")}
	svc, events := newServiceWithNovu(t, novu)
	ctx := withTenant(fixtureTenant)
	if _, err := svc.RegisterWorkflow(ctx, fixtureTenant, notifications.RegisterWorkflowInput{
		Name: "user.password_reset", NovuWorkflowID: "novu_wf_X",
	}); err != nil {
		t.Fatalf("register: %v", err)
	}
	res, err := svc.Send(ctx, fixtureTenant, notifications.SendRequest{
		WorkflowName: "user.password_reset",
		ToUserID:     "user_01HAAAAAAAAAAAAAAAAAAAAAAA",
	})
	if err != nil {
		t.Fatalf("Send must not surface the Novu failure to the caller (queued already): %v", err)
	}
	if !events.has("notification.queued") {
		t.Errorf("missing notification.queued")
	}
	if !events.has("notification.delivery_failed") {
		t.Errorf("missing notification.delivery_failed")
	}
	if events.has("notification.sent") {
		t.Errorf("sent must not fire on failure")
	}
	if res.Notification.Status != notifications.NotificationStatusFailed {
		t.Errorf("status: got %q want failed", res.Notification.Status)
	}
}

// --- workflow update --------------------------------------------------------

func TestService_UpdateWorkflow_EmitsWorkflowUpdated(t *testing.T) {
	svc, _, events := newService(t)
	ctx := withTenant(fixtureTenant)
	wf, err := svc.RegisterWorkflow(ctx, fixtureTenant, notifications.RegisterWorkflowInput{
		Name: "user.password_reset", NovuWorkflowID: "novu_wf_v1",
	})
	if err != nil {
		t.Fatalf("register: %v", err)
	}
	newID := "novu_wf_v2"
	got, err := svc.UpdateWorkflow(ctx, fixtureTenant, wf.ID, notifications.WorkflowPatch{
		NovuWorkflowID: &newID,
	})
	if err != nil {
		t.Fatalf("UpdateWorkflow: %v", err)
	}
	if got.NovuWorkflowID != "novu_wf_v2" {
		t.Errorf("novu workflow id not updated: %q", got.NovuWorkflowID)
	}
	if !events.has("notification_workflow.updated") {
		t.Errorf("missing notification_workflow.updated event")
	}
}

func TestService_UpdateWorkflow_EmptyPatchRejected(t *testing.T) {
	svc, _, _ := newService(t)
	ctx := withTenant(fixtureTenant)
	wf, _ := svc.RegisterWorkflow(ctx, fixtureTenant, notifications.RegisterWorkflowInput{
		Name: "wf", NovuWorkflowID: "n1",
	})
	_, err := svc.UpdateWorkflow(ctx, fixtureTenant, wf.ID, notifications.WorkflowPatch{})
	if !errors.Is(err, notifications.ErrInvalidInput) {
		t.Errorf("expected ErrInvalidInput on empty patch, got %v", err)
	}
}
