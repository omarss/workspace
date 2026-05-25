package notifications

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/id"
)

const (
	channelNameMaxLen = 64
	workflowNameMax   = 64
	descriptionMaxLen = 256
)

// Service is the notifications application service. It validates input,
// runs the BYOK envelope walker (via the repository), and emits outbox
// events that the worker consumes.
//
// When Novu + Users are wired (production binary), Send takes the sync
// trigger path: the request is forwarded to Novu immediately and the
// service emits notification.sent or notification.delivery_failed before
// returning. When either dependency is nil (most unit tests), Send falls
// back to the queue-only behaviour and the async worker promotes the row.
// ADR 013 enumerates the eight outbox event types this module emits.
type Service struct {
	repo         Repository
	events       EventPublisher
	novu         NovuClient
	users        UserLookup
	deploymentID string
	now          func() time.Time
}

// Config groups Service constructor parameters.
type Config struct {
	Repo   Repository
	Events EventPublisher
	// Novu + Users are optional. When set, Service.Send performs a sync
	// trigger to Novu and emits notification.sent / .delivery_failed on
	// the result. When unset, Send only emits notification.queued and the
	// worker handles dispatch asynchronously. cmd/dataplane wires both
	// when NOTIFICATIONS_ENABLED=true.
	Novu         NovuClient
	Users        UserLookup
	DeploymentID string
}

// NewService constructs a Service from cfg.
func NewService(cfg Config) *Service {
	return &Service{
		repo:         cfg.Repo,
		events:       cfg.Events,
		novu:         cfg.Novu,
		users:        cfg.Users,
		deploymentID: cfg.DeploymentID,
		now:          time.Now,
	}
}

// WithClock substitutes the clock; tests only.
func (s *Service) WithClock(now func() time.Time) *Service {
	s.now = now
	return s
}

// ---------------------------------------------------------------------------
// Channels
// ---------------------------------------------------------------------------

// CreateChannelInput is the application-level input to CreateChannel. The
// handler builds it from the OpenAPI-generated request struct.
type CreateChannelInput struct {
	Provider     ChannelProvider
	Name         string
	Config       map[string]string
	IsDefaultFor []string
	Credentials  CredentialsBundle
}

// CreateChannel persists a new BYOK channel. Validates provider + creds
// shape before delegating to the repository; the repository runs the
// strict-mode envelope walker.
func (s *Service) CreateChannel(ctx context.Context, tenantID string, in CreateChannelInput) (Channel, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Channel{}, err
	}
	if !in.Provider.Valid() {
		return Channel{}, ErrInvalidProvider
	}
	if err := validateName(in.Name); err != nil {
		return Channel{}, err
	}
	if err := ValidateCredentialsForProvider(in.Provider, in.Credentials); err != nil {
		return Channel{}, err
	}
	payload, err := MarshalCredentials(in.Credentials)
	if err != nil {
		return Channel{}, err
	}
	now := s.now().UTC()
	ch := Channel{
		ID:           id.New(id.PrefixChannel),
		TenantID:     tenantID,
		Provider:     in.Provider,
		Name:         in.Name,
		Config:       in.Config,
		Status:       ChannelStatusActive,
		IsDefaultFor: in.IsDefaultFor,
		Secrets:      payload,
		RowSeq:       1,
		CreatedAt:    now,
		UpdatedAt:    now,
	}
	created, err := s.repo.CreateChannel(ctx, ch)
	if err != nil {
		return Channel{}, err
	}
	// Sanitise the in-memory return so the handler cannot accidentally
	// echo plaintext creds in the response. The repo also clears
	// Secrets via the walker; this is belt-and-braces.
	created.Secrets = ""
	_ = s.events.Publish(ctx, "notification_channel.created", created.TenantID, map[string]any{
		"channel_id": created.ID,
		"provider":   string(created.Provider),
	})
	return created, nil
}

// GetChannel returns the channel if it belongs to the caller's tenant.
// The returned struct never carries plaintext credentials — the
// repository clears Secrets after the kid-checked decrypt.
func (s *Service) GetChannel(ctx context.Context, tenantID, channelID string) (Channel, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Channel{}, err
	}
	ch, err := s.repo.GetChannel(ctx, tenantID, channelID)
	if err != nil {
		return Channel{}, err
	}
	ch.Secrets = ""
	return ch, nil
}

// ListChannels enumerates channels in the caller's tenant.
func (s *Service) ListChannels(ctx context.Context, tenantID string, limit int) ([]Channel, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return nil, err
	}
	if limit <= 0 || limit > 200 {
		limit = 25
	}
	chs, err := s.repo.ListChannels(ctx, tenantID, limit)
	if err != nil {
		return nil, err
	}
	for i := range chs {
		chs[i].Secrets = ""
	}
	return chs, nil
}

// UpdateChannel applies a metadata-only patch. Per ADR 017 the patch
// path NEVER carries credentials — rotation is a distinct verb.
func (s *Service) UpdateChannel(ctx context.Context, tenantID, channelID string, expectedSeq int64, patch ChannelPatch) (Channel, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Channel{}, err
	}
	if patch.Name != nil {
		if err := validateName(*patch.Name); err != nil {
			return Channel{}, err
		}
	}
	if patch.Status != nil && !patch.Status.Valid() {
		return Channel{}, ErrInvalidInput
	}
	updated, err := s.repo.UpdateChannel(ctx, tenantID, channelID, expectedSeq, patch)
	if err != nil {
		return Channel{}, err
	}
	updated.Secrets = ""
	_ = s.events.Publish(ctx, "notification_channel.updated", updated.TenantID, map[string]any{"channel_id": updated.ID})
	return updated, nil
}

// DeleteChannel soft-deletes a channel under optimistic concurrency.
func (s *Service) DeleteChannel(ctx context.Context, tenantID, channelID string, expectedSeq int64) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	if err := s.repo.DeleteChannel(ctx, tenantID, channelID, expectedSeq); err != nil {
		return err
	}
	_ = s.events.Publish(ctx, "notification_channel.deleted", tenantID, map[string]any{"channel_id": channelID})
	return nil
}

// RotateChannelCredentials swaps in new credentials. The new payload
// flows through the envelope walker like Create; the row's row_seq is
// bumped and last_rotated_at is stamped. Emits a rotation audit event.
//
// Per ADR 017 this is the ONLY endpoint that accepts credentials after
// the initial Create.
func (s *Service) RotateChannelCredentials(ctx context.Context, tenantID, channelID string, newCreds CredentialsBundle) (Channel, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Channel{}, err
	}
	// Confirm the channel exists + belongs to tenant before validating
	// the new payload so the error ordering matches GetChannel.
	existing, err := s.repo.GetChannel(ctx, tenantID, channelID)
	if err != nil {
		return Channel{}, err
	}
	if err := ValidateCredentialsForProvider(existing.Provider, newCreds); err != nil {
		return Channel{}, err
	}
	payload, err := MarshalCredentials(newCreds)
	if err != nil {
		return Channel{}, err
	}
	rotated, err := s.repo.RotateChannelSecrets(ctx, tenantID, channelID, payload)
	if err != nil {
		return Channel{}, err
	}
	rotated.Secrets = ""
	_ = s.events.Publish(ctx, "notification_channel.rotated", rotated.TenantID, map[string]any{
		"channel_id":      rotated.ID,
		"provider":        string(rotated.Provider),
		"last_rotated_at": rotated.LastRotatedAt,
	})
	return rotated, nil
}

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------

// RegisterWorkflowInput is the input to RegisterWorkflow.
type RegisterWorkflowInput struct {
	Name           string
	NovuWorkflowID string
	Description    string
}

// RegisterWorkflow records the (name, novu_workflow_id) mapping in the
// platform DB. Novu itself owns the template definition.
func (s *Service) RegisterWorkflow(ctx context.Context, tenantID string, in RegisterWorkflowInput) (Workflow, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Workflow{}, err
	}
	if err := validateWorkflowName(in.Name); err != nil {
		return Workflow{}, err
	}
	if strings.TrimSpace(in.NovuWorkflowID) == "" {
		return Workflow{}, ErrInvalidInput
	}
	if len(in.Description) > descriptionMaxLen {
		return Workflow{}, ErrInvalidInput
	}
	wf := Workflow{
		ID:             id.New(id.PrefixWorkflow),
		TenantID:       tenantID,
		Name:           in.Name,
		NovuWorkflowID: in.NovuWorkflowID,
		Description:    in.Description,
		CreatedAt:      s.now().UTC(),
	}
	created, err := s.repo.RegisterWorkflow(ctx, wf)
	if err != nil {
		return Workflow{}, err
	}
	_ = s.events.Publish(ctx, "notification_workflow.created", tenantID, map[string]any{
		"workflow_id":      created.ID,
		"workflow_name":    created.Name,
		"novu_workflow_id": created.NovuWorkflowID,
	})
	return created, nil
}

// ListWorkflows returns workflows registered in the caller's tenant.
func (s *Service) ListWorkflows(ctx context.Context, tenantID string) ([]Workflow, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return nil, err
	}
	return s.repo.ListWorkflows(ctx, tenantID)
}

// UpdateWorkflow applies a partial PATCH to a workflow registry row. At
// least one of NovuWorkflowID / Description MUST be set; an empty patch
// returns ErrInvalidInput so callers cannot trigger silent no-op writes.
// Emits notification_workflow.updated per ADR 013.
func (s *Service) UpdateWorkflow(ctx context.Context, tenantID, workflowID string, patch WorkflowPatch) (Workflow, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Workflow{}, err
	}
	if patch.NovuWorkflowID == nil && patch.Description == nil {
		return Workflow{}, ErrInvalidInput
	}
	if patch.NovuWorkflowID != nil && strings.TrimSpace(*patch.NovuWorkflowID) == "" {
		return Workflow{}, ErrInvalidInput
	}
	if patch.Description != nil && len(*patch.Description) > descriptionMaxLen {
		return Workflow{}, ErrInvalidInput
	}
	updated, err := s.repo.UpdateWorkflow(ctx, tenantID, workflowID, patch)
	if err != nil {
		return Workflow{}, err
	}
	_ = s.events.Publish(ctx, "notification_workflow.updated", tenantID, map[string]any{
		"workflow_id":      updated.ID,
		"workflow_name":    updated.Name,
		"novu_workflow_id": updated.NovuWorkflowID,
	})
	return updated, nil
}

// ---------------------------------------------------------------------------
// Send
// ---------------------------------------------------------------------------

// Send queues a notification. Returns 202-style: the caller gets back the
// queued row immediately and the worker promotes it via the outbox.
//
// The payload is envelope-encrypted before any DB write (repo runs the
// walker). Status transitions live on the worker — handlers never mutate
// them directly.
func (s *Service) Send(ctx context.Context, tenantID string, req SendRequest) (SendResult, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return SendResult{}, err
	}
	if strings.TrimSpace(req.WorkflowName) == "" || strings.TrimSpace(req.ToUserID) == "" {
		return SendResult{}, ErrInvalidInput
	}
	wf, err := s.repo.GetWorkflowByName(ctx, tenantID, req.WorkflowName)
	if err != nil {
		if errors.Is(err, ErrNotFound) {
			return SendResult{}, ErrWorkflowNotRegistered
		}
		return SendResult{}, err
	}
	payloadJSON := "{}"
	if len(req.Payload) > 0 {
		b, marshalErr := json.Marshal(req.Payload)
		if marshalErr != nil {
			return SendResult{}, ErrInvalidInput
		}
		payloadJSON = string(b)
	}
	now := s.now().UTC()
	n := Notification{
		ID:           id.New(id.PrefixNotification),
		TenantID:     tenantID,
		WorkflowName: req.WorkflowName,
		ToUserID:     req.ToUserID,
		Status:       NotificationStatusQueued,
		Payload:      payloadJSON,
		QueuedAt:     now,
		RowSeq:       1,
	}
	created, err := s.repo.CreateNotification(ctx, n)
	if err != nil {
		return SendResult{}, err
	}
	created.Payload = "" // do not echo plaintext on the response
	_ = s.events.Publish(ctx, "notification.queued", created.TenantID, map[string]any{
		"notification_id":  created.ID,
		"workflow_name":    created.WorkflowName,
		"novu_workflow_id": wf.NovuWorkflowID,
		"to_user_id":       created.ToUserID,
	})

	// Sync dispatch is only attempted when both the Novu adapter and the
	// user-lookup port are wired (production binary). The unit-test
	// surface stays queue-only so existing fakes keep working.
	if s.novu != nil && s.users != nil {
		return s.dispatchNow(ctx, created, wf.NovuWorkflowID, req.Payload), nil
	}
	return SendResult{Notification: created}, nil
}

// dispatchNow is the synchronous Novu trigger path. It resolves the
// subscriber attributes via the UserLookup port, calls Novu, and emits
// either notification.sent or notification.delivery_failed per ADR 013.
// The notification row's status is updated to match. The outbox event +
// status update use best-effort error handling — a failure to write the
// status row is logged but the API response still carries the result, so
// callers always see a deterministic terminal state for sync sends.
func (s *Service) dispatchNow(ctx context.Context, n Notification, novuWorkflowID string, payload map[string]any) SendResult {
	// Ensure the Novu subscriber exists. The subscriber id is the platform
	// user_id so no PII leaves the platform unless the lookup port returns
	// optional name / email for template variables.
	info, lookupErr := s.users.LookupUser(ctx, n.TenantID, n.ToUserID)
	if lookupErr == nil {
		_ = s.novu.EnsureSubscriber(ctx, info.UserID, info.Email, info.Name)
	}

	novuID, sendErr := s.novu.TriggerWorkflow(ctx, novuWorkflowID, n.ToUserID, payload)
	if sendErr != nil {
		reason := sendErr.Error()
		updated, _ := s.repo.UpdateNotificationStatus(ctx, n.ID, NotificationStatusFailed, &reason, nil)
		_ = s.events.Publish(ctx, "notification.delivery_failed", n.TenantID, map[string]any{
			"notification_id": n.ID,
			"workflow_name":   n.WorkflowName,
			"to_user_id":      n.ToUserID,
			"reason":          reason,
		})
		// Surface the failure on the response struct so the handler can
		// translate; existing callers that ignore terminal status keep
		// working because the queued+id pair is also set.
		if updated.ID != "" {
			updated.Payload = ""
			return SendResult{Notification: updated}
		}
		failed := n
		failed.Status = NotificationStatusFailed
		failed.FailureReason = &reason
		return SendResult{Notification: failed}
	}

	updated, _ := s.repo.UpdateNotificationStatus(ctx, n.ID, NotificationStatusSent, nil, &novuID)
	_ = s.events.Publish(ctx, "notification.sent", n.TenantID, map[string]any{
		"notification_id":     n.ID,
		"workflow_name":       n.WorkflowName,
		"to_user_id":          n.ToUserID,
		"novu_transaction_id": novuID,
	})
	if updated.ID == "" {
		// Repository did not echo the row back; synthesize the terminal
		// state from the original record so the response remains useful.
		sent := n
		sent.Status = NotificationStatusSent
		sent.NovuTransactionID = &novuID
		return SendResult{Notification: sent}
	}
	updated.Payload = ""
	return SendResult{Notification: updated}
}

// GetNotification returns a single notification row in the caller tenant.
func (s *Service) GetNotification(ctx context.Context, tenantID, notificationID string) (Notification, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Notification{}, err
	}
	n, err := s.repo.GetNotification(ctx, tenantID, notificationID)
	if err != nil {
		return Notification{}, err
	}
	n.Payload = ""
	return n, nil
}

// ListNotifications returns notifications for the caller tenant.
func (s *Service) ListNotifications(ctx context.Context, tenantID string, limit int, cur *ListCursor) ([]Notification, bool, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return nil, false, err
	}
	if limit <= 0 || limit > 200 {
		limit = 25
	}
	out, hasMore, err := s.repo.ListNotifications(ctx, tenantID, limit, cur)
	if err != nil {
		return nil, false, err
	}
	for i := range out {
		out[i].Payload = ""
	}
	return out, hasMore, nil
}

// ---------------------------------------------------------------------------
// validation
// ---------------------------------------------------------------------------

func validateName(name string) error {
	name = strings.TrimSpace(name)
	if name == "" || len(name) > channelNameMaxLen {
		return ErrInvalidInput
	}
	return nil
}

func validateWorkflowName(name string) error {
	name = strings.TrimSpace(name)
	if name == "" || len(name) > workflowNameMax {
		return ErrInvalidInput
	}
	return nil
}
