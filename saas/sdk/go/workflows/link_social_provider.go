package workflows

import (
	"context"
	"time"

	dp "github.com/omarss/saas/sdk/go/dataplane"
	"github.com/omarss/saas/sdk/go/internal/idem"
)

// LinkSocialProviderInput targets POST /v1/users/{user_id}/social-providers.
//
// Per ADR 014 (Phase 5): the platform NEVER calls Keycloak's
// CreateUserFederatedIdentity from a user-facing endpoint (no
// proof-of-possession). The data plane mints Keycloak's hashed link URL
// instead; the caller redirects the user's browser there and Keycloak
// completes the OAuth dance with the external IdP.
type LinkSocialProviderInput struct {
	UserID   string
	Provider string // one of: google, github, apple
	ReturnTo string
}

// SocialProviderLink is the workflow result. The AuthorizationURL is what
// the caller should redirect the user-agent to; State is a short-lived
// CSRF token bound to the link.
type SocialProviderLink struct {
	AuthorizationURL string
	State            string
	ExpiresAt        time.Time
}

// LinkSocialProvider wraps the link-flow endpoint. Auto-generates an
// Idempotency-Key. Returns 202 Accepted on success.
func LinkSocialProvider(
	ctx context.Context,
	client *dp.ClientWithResponses,
	in LinkSocialProviderInput,
	opts ...Option,
) (SocialProviderLink, error) {
	o := collect(opts)
	key := o.idemKey
	if key == "" {
		key = idem.New()
	}

	body := dp.LinkSocialProviderRequest{
		Provider: dp.LinkSocialProviderRequestProvider(in.Provider),
		ReturnTo: in.ReturnTo,
	}
	res, err := client.LinkSocialProviderWithResponse(ctx, in.UserID,
		&dp.LinkSocialProviderParams{IdempotencyKey: dp.IdempotencyKey(key)}, body)
	if err != nil {
		return SocialProviderLink{}, err
	}
	if res.StatusCode() != 202 || res.JSON202 == nil {
		return SocialProviderLink{}, parseProblem(res.StatusCode(), res.Body)
	}
	return SocialProviderLink{
		AuthorizationURL: res.JSON202.AuthorizationUrl,
		State:            res.JSON202.State,
		ExpiresAt:        res.JSON202.ExpiresAt,
	}, nil
}
