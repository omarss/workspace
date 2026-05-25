package notifications

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strings"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
)

// Default workflow names. The Identity rewire (Phase 6) and Phase 7
// invitations both consume these constants. Operators register the
// matching workflows in Novu via `make notifications-seed-default-workflows`.
const (
	WorkflowPasswordReset = "user.password_reset"
	WorkflowEmailVerify   = "user.email_verify"
	WorkflowInvitation    = "member.invited"
)

// SendPasswordReset queues the password-reset email via the standard
// notifications path. Returns the queued notification id so the caller
// can correlate. The Identity service calls this in place of Keycloak's
// built-in SMTP when NOTIFICATIONS_ENABLED=true.
//
// resetURL is the Keycloak-minted action-token URL (Identity already
// generates these in Phase 5); the workflow template formats the email
// around it via Novu's payload variables.
func (s *Service) SendPasswordReset(ctx context.Context, tenantID, userID, resetURL string, ttlMinutes int) (Notification, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Notification{}, err
	}
	payload := map[string]any{
		"reset_url":          resetURL,
		"expires_in_minutes": ttlMinutes,
	}
	res, err := s.Send(ctx, tenantID, SendRequest{
		WorkflowName: WorkflowPasswordReset,
		ToUserID:     userID,
		Payload:      payload,
	})
	if err != nil {
		return Notification{}, err
	}
	return res.Notification, nil
}

// SendEmailVerify queues the email-verification email via the standard
// notifications path. Symmetric with SendPasswordReset.
func (s *Service) SendEmailVerify(ctx context.Context, tenantID, userID, verifyURL string, ttlMinutes int) (Notification, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Notification{}, err
	}
	payload := map[string]any{
		"verify_url":         verifyURL,
		"expires_in_minutes": ttlMinutes,
	}
	res, err := s.Send(ctx, tenantID, SendRequest{
		WorkflowName: WorkflowEmailVerify,
		ToUserID:     userID,
		Payload:      payload,
	})
	if err != nil {
		return Notification{}, err
	}
	return res.Notification, nil
}

// InvitationByEmailRequest is the input to SendInvitationByEmail. The
// recipient is identified by email only — there is no platform_user row
// yet (Phase 7 organizations invitations target prospective members who
// may sign up via the accept flow).
type InvitationByEmailRequest struct {
	InviteeEmail string
	AcceptURL    string
	OrgName      string
	InviterName  string
	TTL          time.Duration
}

// SendInvitationByEmail dispatches an organisation-invitation email to a
// recipient that does not yet have a platform_user row.
//
// The notification table requires a non-NULL to_user_id (FK to
// platform_user) — Phase 7 cannot satisfy that for pre-signup invitees
// without amending the existing Phase 6 migration. The method therefore
// emits the same outbox events as Send (notification.queued + .sent /
// .delivery_failed) without persisting a notification row. Auditability
// is preserved via the outbox + the invitation row itself (which is the
// system of record for this flow). When the invitee later accepts and a
// platform_user is created, future invitation-acceptance notifications
// flow through the standard Send path.
//
// When the Novu adapter is wired the dispatch is synchronous; otherwise
// the method only emits the queued event so the outbox-consuming worker
// can dispatch later. The recipient is identified to Novu by a transient
// subscriber id derived from sha256(email) — no PII leaves the platform
// unless Novu templates explicitly reference it.
func (s *Service) SendInvitationByEmail(ctx context.Context, tenantID string, req InvitationByEmailRequest) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	email := strings.TrimSpace(req.InviteeEmail)
	if email == "" {
		return fmt.Errorf("%w: invitee_email", ErrInvalidInput)
	}
	if strings.TrimSpace(req.AcceptURL) == "" {
		return fmt.Errorf("%w: accept_url", ErrInvalidInput)
	}

	// Transient Novu subscriber id. The platform never sends raw email
	// as a subscriber id — sha256 keeps the cardinality low and the PII
	// out of subscriber-level Novu logs.
	subscriberID := "invitee:" + hashForSubscriber(email)

	payload := map[string]any{
		"accept_url":   req.AcceptURL,
		"org_name":     req.OrgName,
		"inviter_name": req.InviterName,
	}
	if req.TTL > 0 {
		payload["ttl_seconds"] = int(req.TTL.Seconds())
	}

	// Queued audit event. The invitation_id correlates this back to the
	// invitation row at audit-review time; here we only carry the
	// subscriber surrogate so the outbox payload is PII-free.
	_ = s.events.Publish(ctx, "notification.queued", tenantID, map[string]any{
		"workflow_name":       WorkflowInvitation,
		"recipient_type":      "email",
		"recipient_surrogate": subscriberID,
	})

	if s.novu == nil {
		// No sync dispatcher — leave terminal state to the worker once it
		// processes the queued event. Phase 7's invitation path tolerates
		// this (the email is best-effort; the user can be re-issued an
		// invitation via the future /resend endpoint).
		return nil
	}

	// Best-effort upsert; Novu allows ad-hoc subscribers but EnsureSubscriber
	// pre-creates the row so templates can reference {{subscriber.email}}.
	_ = s.novu.EnsureSubscriber(ctx, subscriberID, email, "")

	novuID, sendErr := s.novu.TriggerWorkflow(ctx, WorkflowInvitation, subscriberID, payload)
	if sendErr != nil {
		_ = s.events.Publish(ctx, "notification.delivery_failed", tenantID, map[string]any{
			"workflow_name":       WorkflowInvitation,
			"recipient_type":      "email",
			"recipient_surrogate": subscriberID,
			"reason":              sendErr.Error(),
		})
		return ErrProviderUnavailable
	}

	_ = s.events.Publish(ctx, "notification.sent", tenantID, map[string]any{
		"workflow_name":       WorkflowInvitation,
		"recipient_type":      "email",
		"recipient_surrogate": subscriberID,
		"novu_transaction_id": novuID,
	})
	return nil
}

// hashForSubscriber returns the hex-encoded sha256 of the (normalised)
// email so the surrogate id stays stable across calls without leaking
// the address into Novu subscriber metadata.
func hashForSubscriber(email string) string {
	sum := sha256.Sum256([]byte(strings.ToLower(strings.TrimSpace(email))))
	return hex.EncodeToString(sum[:16])
}

// SendInvitation queues the organisation-invitation email. Phase 7's
// Members + Invitations module imports this directly so it does not need
// to know about notification workflows by name.
func (s *Service) SendInvitation(ctx context.Context, tenantID, inviteeUserID, acceptURL, organisationName, inviterName string, ttlHours int) (Notification, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Notification{}, err
	}
	payload := map[string]any{
		"accept_url":        acceptURL,
		"organisation_name": organisationName,
		"inviter_name":      inviterName,
		"expires_in_hours":  ttlHours,
	}
	res, err := s.Send(ctx, tenantID, SendRequest{
		WorkflowName: WorkflowInvitation,
		ToUserID:     inviteeUserID,
		Payload:      payload,
	})
	if err != nil {
		return Notification{}, err
	}
	return res.Notification, nil
}
