// Package notifications is the Phase 6 vertical slice: BYOK vendor channels
// + workflow registry + send queue wrapping a self-hosted Novu v3.15.0
// stack. Hexagonal layout mirrors Phases 2 + 5:
//
//	handler.go        HTTP boundary (oapi-codegen StrictServerInterface)
//	service.go        application orchestration
//	ports.go          Repository + NovuClient + EventPublisher
//	repo_pgx.go       pgx-backed Repository implementation
//	novu_adapter.go   handwritten REST client for the Novu HTTP API
//	creds.go          per-provider credential structs + JSON helpers
//	password_reset.go feature-flagged entry point for Identity rewire
//	domain.go         Channel / Workflow / Notification + envelope siblings
//	errors.go         sentinel errors → RFC 9457 problems
//
// BYOK handling (ADR 017): every channel's Secrets payload is treated as
// PII/sensitive. The Go struct carries a sibling SecretsEnvelope of type
// crypto.Envelope; the repository runs crypto.EncryptPIIFieldsStrict before
// every INSERT / UPDATE so a missing sibling on the domain struct fails
// closed (cannot leak plaintext through a write path). AAD is bound to the
// deployment_id || resource_type || resource_id triple per CONVENTIONS.md
// §10.1 — see repo_pgx.go for the call site.
package notifications

import (
	"time"

	"github.com/omarss/saas/internal/platform/crypto"
	"github.com/omarss/saas/internal/platform/etag"
)

// ChannelProvider enumerates the BYOK channel providers MVP supports.
// Adding a new provider requires (a) an ADR, (b) a new credential struct
// in creds.go, and (c) extending Provider.Valid().
type ChannelProvider string

// Allowed channel providers in MVP. See ADR 013 + 017.
const (
	ProviderSMTP     ChannelProvider = "smtp"
	ProviderSendGrid ChannelProvider = "sendgrid"
	ProviderSES      ChannelProvider = "ses"
	ProviderInApp    ChannelProvider = "in_app"
)

// Valid reports whether p is one of the MVP-allowed channel providers.
func (p ChannelProvider) Valid() bool {
	switch p {
	case ProviderSMTP, ProviderSendGrid, ProviderSES, ProviderInApp:
		return true
	}
	return false
}

// ChannelStatus is the lifecycle state for a channel row. "disabled" hides
// it from the workflow dispatcher; the row stays in the table for audit.
type ChannelStatus string

// Allowed channel statuses.
const (
	ChannelStatusActive   ChannelStatus = "active"
	ChannelStatusDisabled ChannelStatus = "disabled"
)

// Valid reports whether s is one of the platform's allowed states.
func (s ChannelStatus) Valid() bool {
	switch s {
	case ChannelStatusActive, ChannelStatusDisabled:
		return true
	}
	return false
}

// NotificationStatus is the lifecycle state for a single notification.
type NotificationStatus string

// Allowed notification statuses. queued → sent → delivered, or → failed.
const (
	NotificationStatusQueued    NotificationStatus = "queued"
	NotificationStatusSent      NotificationStatus = "sent"
	NotificationStatusDelivered NotificationStatus = "delivered"
	NotificationStatusFailed    NotificationStatus = "failed"
)

// Valid reports whether s is one of the platform's allowed statuses.
func (s NotificationStatus) Valid() bool {
	switch s {
	case NotificationStatusQueued, NotificationStatusSent,
		NotificationStatusDelivered, NotificationStatusFailed:
		return true
	}
	return false
}

// Channel is the BYOK vendor configuration row.
//
// CRITICAL: Secrets is the JSON-encoded provider-shaped credential payload
// (e.g. {"password":"…"} for SMTP, {"api_key":"…"} for SendGrid). It is
// tagged pii/sensitive so the strict-mode walker requires the
// SecretsEnvelope sibling — adding a new sensitive field MUST also add the
// sibling or the persistence path fails closed.
//
// Config holds non-secret per-provider settings (host, port, from, region).
// These remain plaintext columns.
type Channel struct {
	ID           string
	TenantID     string
	Provider     ChannelProvider
	Name         string
	Config       map[string]string
	Status       ChannelStatus
	IsDefaultFor []string

	// Decrypted in-memory only; cleared after the walker runs on writes.
	Secrets         string `pii:"true" sensitive:"true"`
	SecretsEnvelope crypto.Envelope

	NovuIntegrationID *string
	LastRotatedAt     *time.Time
	RowSeq            int64
	CreatedAt         time.Time
	UpdatedAt         time.Time
	DeletedAt         *time.Time
}

// ETag returns the platform's Weak ETag for this channel.
func (c Channel) ETag() string { return etag.Format(c.RowSeq) }

// HasSecrets reports whether the channel has credential material persisted.
// Used by the handler to emit credentials_present without leaking plaintext.
func (c Channel) HasSecrets() bool {
	return !c.SecretsEnvelope.IsZero()
}

// ChannelPatch carries optional PATCH fields for the meta-only update
// endpoint. Per ADR 017 credentials never flow through PATCH; rotation is
// a separate verb.
type ChannelPatch struct {
	Name          *string
	Status        *ChannelStatus
	IsDefaultFor  []string
	PatchDefaults bool
	Config        map[string]string
	PatchConfig   bool
}

// Workflow is the platform's name → Novu workflow id mapping. Templates
// themselves live in Novu; the platform stores no template bodies.
type Workflow struct {
	ID             string
	TenantID       string
	Name           string
	NovuWorkflowID string
	Description    string
	CreatedAt      time.Time
}

// WorkflowPatch carries the optional PATCH fields for
// PATCH /v1/notification-workflows/{workflow_id}. Renaming is not
// supported in v1; the immutable `name` is the cross-deployment lookup key.
type WorkflowPatch struct {
	NovuWorkflowID *string
	Description    *string
}

// Notification is one queued / sent / delivered / failed record. Payload
// is the encrypted blob the workflow renderer consumes; the field is the
// JSON-encoded plaintext on the in-memory struct (cleared post-write).
type Notification struct {
	ID                string
	TenantID          string
	WorkflowName      string
	ToUserID          string
	Status            NotificationStatus
	Payload           string `pii:"true" sensitive:"true"`
	PayloadEnvelope   crypto.Envelope
	NovuTransactionID *string
	QueuedAt          time.Time
	SentAt            *time.Time
	DeliveredAt       *time.Time
	FailedAt          *time.Time
	FailureReason     *string
	RowSeq            int64
}

// ListCursor is the decoded form of the opaque cursor returned from
// /v1/notifications. Repository.ListNotifications uses (QueuedAt, ID) as
// a strict tuple less-than to keyset-paginate.
type ListCursor struct {
	QueuedAt time.Time
	ID       string
}

// SendRequest is the application-level shape passed to Service.Send. The
// handler builds it from the OpenAPI-generated request body.
type SendRequest struct {
	WorkflowName string
	ToUserID     string
	Payload      map[string]any
}

// SendResult is what Service.Send returns to the handler. Phase 6 ships
// queued+id only — the worker promotes the row to sent/delivered/failed
// out of band by consuming the notification.queued outbox event.
type SendResult struct {
	Notification Notification
}
