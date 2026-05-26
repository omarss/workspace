package workflows

import (
	"context"

	openapi_types "github.com/oapi-codegen/runtime/types"

	dp "github.com/omarss/saas/sdk/go/dataplane"
	"github.com/omarss/saas/sdk/go/internal/idem"
)

// InviteMemberInput targets POST /v1/organizations/{org}/invitations.
//
// Per Phase 7 (commit "fix — wire ... SendInvitationByEmail"), the workflow
// addresses invitees by their EMAIL — the invitee may not yet have a
// platform user account; the email triggers Novu, the user clicks the link
// and KC creates the account on accept. ExpiresInSeconds and
// ProposedRoleID are optional; pass 0 / "" to leave them unset.
type InviteMemberInput struct {
	OrganizationID   string
	InviteeEmail     string
	ProposedRoleID   string
	ExpiresInSeconds int
}

// Invited is the workflow's success payload. AcceptURL and State both
// contain the one-time plaintext invitation token and MUST be treated as
// secrets — the platform redacts them from audit and never re-emits them.
type Invited struct {
	Invitation dp.Invitation
	AcceptURL  string
	State      string
}

// InviteMember wraps the createInvitation endpoint. The HTTP response is
// 202 Accepted because email dispatch happens via the Notifications
// outbox.
func InviteMember(
	ctx context.Context,
	client *dp.ClientWithResponses,
	in InviteMemberInput,
	opts ...Option,
) (Invited, error) {
	o := collect(opts)
	key := o.idemKey
	if key == "" {
		key = idem.New()
	}

	body := dp.CreateInvitationRequest{
		InviteeEmail: openapi_types.Email(in.InviteeEmail),
	}
	if in.ProposedRoleID != "" {
		rid := in.ProposedRoleID
		body.ProposedRoleId = &rid
	}
	if in.ExpiresInSeconds > 0 {
		s := in.ExpiresInSeconds
		body.ExpiresInSeconds = &s
	}

	res, err := client.CreateInvitationWithResponse(ctx, in.OrganizationID,
		&dp.CreateInvitationParams{IdempotencyKey: dp.IdempotencyKey(key)}, body)
	if err != nil {
		return Invited{}, err
	}
	if res.StatusCode() != 202 || res.JSON202 == nil {
		return Invited{}, parseProblem(res.StatusCode(), res.Body)
	}
	return Invited{
		Invitation: res.JSON202.Data,
		AcceptURL:  res.JSON202.AcceptUrl,
		State:      res.JSON202.State,
	}, nil
}
