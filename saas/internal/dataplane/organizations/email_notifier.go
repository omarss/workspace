package organizations

import (
	"context"
	"time"

	"github.com/omarss/saas/internal/dataplane/notifications"
)

// NotificationsEmailNotifier bridges the organizations.EmailNotifier port
// to the Phase 6 notifications.Service. Invitations target an email
// address — not a pre-existing platform_user — so the bridge calls
// notifications.SendInvitationByEmail (added in Phase 7) instead of the
// user-id-bound SendInvitation.
//
// The adapter is intentionally narrow: it transforms the application-
// level SendInvitationInput into notifications.InvitationByEmailRequest
// and forwards the call. Any future Novu template fields land on the
// notifications side without dragging the organizations module into
// per-channel knowledge.
type NotificationsEmailNotifier struct {
	svc *notifications.Service
}

// NewNotificationsEmailNotifier wires the adapter.
func NewNotificationsEmailNotifier(svc *notifications.Service) *NotificationsEmailNotifier {
	return &NotificationsEmailNotifier{svc: svc}
}

// SendInvitation implements organizations.EmailNotifier.
func (n *NotificationsEmailNotifier) SendInvitation(ctx context.Context, in SendInvitationInput) error {
	if n == nil || n.svc == nil {
		// Adapter not wired — operate as a no-op so the invitation create
		// path is not broken in dev / test where Notifications is disabled.
		// The service layer already logs that the notifier is nil-aware.
		return nil
	}
	var ttl time.Duration
	if !in.ExpiresAt.IsZero() {
		ttl = time.Until(in.ExpiresAt)
		if ttl < 0 {
			ttl = 0
		}
	}
	return n.svc.SendInvitationByEmail(ctx, in.TenantID, notifications.InvitationByEmailRequest{
		InviteeEmail: in.InviteeEmail,
		AcceptURL:    in.AcceptURL,
		OrgName:      in.OrganizationName,
		InviterName:  in.InviterName,
		TTL:          ttl,
	})
}
