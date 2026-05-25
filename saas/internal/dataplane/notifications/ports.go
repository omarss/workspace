package notifications

import "context"

// Repository abstracts persistence so the service layer can be unit-tested
// without a real Postgres. The pgx implementation lives in repo_pgx.go.
type Repository interface {
	CreateChannel(ctx context.Context, c Channel) (Channel, error)
	GetChannel(ctx context.Context, tenantID, channelID string) (Channel, error)
	GetChannelByName(ctx context.Context, tenantID, name string) (Channel, error)
	ListChannels(ctx context.Context, tenantID string, limit int) ([]Channel, error)
	UpdateChannel(ctx context.Context, tenantID, channelID string, expectedSeq int64, patch ChannelPatch) (Channel, error)
	DeleteChannel(ctx context.Context, tenantID, channelID string, expectedSeq int64) error
	RotateChannelSecrets(ctx context.Context, tenantID, channelID string, newSecrets string) (Channel, error)
	SetChannelNovuIntegrationID(ctx context.Context, channelID, novuIntegrationID string) error

	RegisterWorkflow(ctx context.Context, w Workflow) (Workflow, error)
	GetWorkflowByName(ctx context.Context, tenantID, name string) (Workflow, error)
	ListWorkflows(ctx context.Context, tenantID string) ([]Workflow, error)
	UpdateWorkflow(ctx context.Context, tenantID, workflowID string, patch WorkflowPatch) (Workflow, error)

	CreateNotification(ctx context.Context, n Notification) (Notification, error)
	GetNotification(ctx context.Context, tenantID, id string) (Notification, error)
	ListNotifications(ctx context.Context, tenantID string, limit int, cursor *ListCursor) ([]Notification, bool, error)
	UpdateNotificationStatus(ctx context.Context, id string, status NotificationStatus, failureReason *string, novuTransactionID *string) (Notification, error)
}

// NovuClient is the handwritten REST adapter for Novu v3.15. The surface
// is small on purpose: trigger a workflow for one subscriber, read back
// the resulting notification status, and create / update vendor-credential
// "integrations" inside Novu when a Channel changes.
//
// Auth: the implementation injects an Authorization: ApiKey <key> header
// using the per-Deployment Novu API key loaded from OpenBao KV at
//
//	secret/data/<deployment_id>/notifications/novu_api_key
//
// (Phase 12e provisions the KV path; for local dev the bootstrap script
// writes it after `make novu-bootstrap`.)
type NovuClient interface {
	// TriggerWorkflow asks Novu to dispatch a workflow to a subscriber.
	// The novuSubscriberID is the platform user_id (we use a stable
	// non-PII id so subscriber email never leaves the platform).
	TriggerWorkflow(ctx context.Context, novuWorkflowID, novuSubscriberID string, payload map[string]any) (transactionID string, err error)

	// GetTransactionStatus reads the current status for a previously
	// triggered transaction. Implementations map Novu's status strings
	// onto the platform's NotificationStatus enum.
	GetTransactionStatus(ctx context.Context, transactionID string) (NotificationStatus, error)

	// UpsertIntegration creates or updates a Novu "integration" carrying
	// per-Deployment vendor credentials. The provider names are Novu's
	// own ("nodemailer", "sendgrid", "ses", "novu") — the adapter maps
	// from ChannelProvider to the Novu key before sending. Returns the
	// Novu integration id which is persisted on the Channel row.
	UpsertIntegration(ctx context.Context, novuIntegrationID string, provider ChannelProvider, credentials map[string]any) (string, error)

	// EnsureSubscriber idempotently creates a Novu subscriber for the
	// given platform user_id. Returns nil if the subscriber already
	// exists. Optional fields (email, name) are passed through so Novu
	// can use them in template variables, but the subscriberId remains
	// the platform user_id.
	EnsureSubscriber(ctx context.Context, novuSubscriberID, email, name string) error
}

// EventPublisher is the outbox port. Implementations write to
// outbox_event in the same transaction as the state change. Mirrors the
// Identity / Tenancy modules.
type EventPublisher interface {
	Publish(ctx context.Context, eventType, tenantID string, payload map[string]any) error
}

// UserLookup is the cross-module port the worker uses to resolve a
// notification's to_user_id into the email + name Novu needs as
// subscriber attributes. The Identity service implements it; tests pass
// a stub.
type UserLookup interface {
	LookupUser(ctx context.Context, tenantID, userID string) (UserInfo, error)
}

// UserInfo is the minimal user view consumed by the Novu worker. The
// values are decrypted PII; the worker zeroes the struct after handing
// it to the adapter.
type UserInfo struct {
	UserID string
	Email  string
	Name   string
}
