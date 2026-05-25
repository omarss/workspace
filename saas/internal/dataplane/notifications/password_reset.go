package notifications

import (
	"context"

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
