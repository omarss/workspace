package identity

import (
	"context"
	"errors"
	"net/url"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
)

// StartSocialLogin is the user-facing manual-link entry point. Per ADR 014
// the platform does NOT call CreateUserFederatedIdentity (no proof of
// possession); instead it stores a state row + mints Keycloak's hashed
// link URL. The caller's frontend redirects the user's browser there;
// Keycloak runs the OAuth dance and writes the federated_identity itself.
//
// We do not enforce that the principal in ctx equals userID — the Phase 5
// design lets an operator with the right scope start a link flow on behalf
// of a tenant-bound user. The DB row stores tenant_id; cross-tenant requests
// are still rejected by RLS + AssertTenant.
func (s *Service) StartSocialLogin(ctx context.Context, tenantID, userID string, provider Provider, returnTo, sessionState, issuedFor string) (SocialLoginStartResult, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return SocialLoginStartResult{}, err
	}
	if !provider.Valid() {
		return SocialLoginStartResult{}, ErrInvalidProvider
	}
	if returnTo == "" {
		return SocialLoginStartResult{}, ErrInvalidInput
	}
	if _, err := url.Parse(returnTo); err != nil {
		return SocialLoginStartResult{}, ErrInvalidInput
	}

	// AssertTenant covers principal-tenant binding; verify the user row too
	// so a forged user_id from another tenant cannot leak the URL.
	u, err := s.repo.Get(ctx, tenantID, userID)
	if err != nil {
		return SocialLoginStartResult{}, err
	}
	if u.Status != StatusActive {
		return SocialLoginStartResult{}, ErrUserDisabled
	}

	stateToken, err := randomToken(stateByteLen)
	if err != nil {
		return SocialLoginStartResult{}, err
	}
	nonce, err := randomToken(nonceByteLen)
	if err != nil {
		return SocialLoginStartResult{}, err
	}
	now := s.now().UTC()
	state := SocialLoginState{
		State:          stateToken,
		TenantID:       tenantID,
		PlatformUserID: userID,
		Provider:       provider,
		ReturnTo:       returnTo,
		Nonce:          nonce,
		CreatedAt:      now,
		ExpiresAt:      now.Add(stateTTL),
	}
	if err := s.repo.InsertSocialLoginState(ctx, state); err != nil {
		return SocialLoginStartResult{}, err
	}

	authURL, err := s.provider.StartSocialLogin(ctx, StartSocialLoginArgs{
		Realm:        s.realm,
		ClientID:     s.clientID,
		Provider:     provider,
		Nonce:        nonce,
		SessionState: sessionState,
		IssuedFor:    issuedFor,
		ReturnTo:     returnTo,
	})
	if err != nil {
		return SocialLoginStartResult{}, errors.Join(ErrProviderUnavailable, err)
	}

	return SocialLoginStartResult{
		AuthorizationURL: authURL,
		State:            stateToken,
		ExpiresAt:        state.ExpiresAt,
	}, nil
}

// SocialLoginStartResult is the handler-facing response body.
type SocialLoginStartResult struct {
	AuthorizationURL string
	State            string
	ExpiresAt        time.Time
}

// UnlinkSocialProvider detaches a federated identity. Safe to call directly
// (no proof-of-possession needed to unlink) — see ADR 014.
func (s *Service) UnlinkSocialProvider(ctx context.Context, tenantID, userID string, provider Provider) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	if !provider.Valid() {
		return ErrInvalidProvider
	}
	u, err := s.repo.Get(ctx, tenantID, userID)
	if err != nil {
		return err
	}
	if err := s.provider.UnlinkIdentityProvider(ctx, s.realm, u.KeycloakUserID, provider); err != nil {
		return errors.Join(ErrProviderUnavailable, err)
	}
	if err := s.repo.UnlinkSocialProvider(ctx, tenantID, userID, provider); err != nil {
		return err
	}
	_ = s.events.Publish(ctx, "user.social_unlinked", tenantID, map[string]any{
		"user_id":  userID,
		"provider": string(provider),
	})
	return nil
}

// ListSocialProviders returns the linked providers for a user. Reads from
// the local mapping table — Keycloak is the source of truth on link/unlink,
// but the local copy supports tenant-scoped audit queries without a
// Keycloak round-trip per request.
func (s *Service) ListSocialProviders(ctx context.Context, tenantID, userID string) ([]SocialProvider, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return nil, err
	}
	if _, err := s.repo.Get(ctx, tenantID, userID); err != nil {
		return nil, err
	}
	return s.repo.ListSocialProviders(ctx, tenantID, userID)
}

// CompleteSocialLogin consumes the state row and persists the linked
// identity. Called from /v1/social/callback after Keycloak's broker flow
// returns. Phase 5 does NOT expose the callback through the data plane —
// Keycloak handles the final redirect to return_to. This method is kept on
// the service so the eventual callback handler in Phase 6/12 can wire it
// without re-implementing the state-validation contract.
//
// Note: AssertTenant is intentionally omitted. The tenant is derived from the
// consumed `social_login_state` row, not from caller input. Consuming the
// state token is itself the authentication check — the state row was bound
// to a specific tenant at issuance (StartSocialLogin), so its consumption
// authorises the caller for that exact tenant.
func (s *Service) CompleteSocialLogin(ctx context.Context, stateToken, externalSubject string) (SocialLoginState, error) {
	state, err := s.repo.ConsumeSocialLoginState(ctx, stateToken)
	if err != nil {
		return SocialLoginState{}, err
	}
	if state.StateConsumed() {
		return SocialLoginState{}, ErrStateAlreadyUsed
	}
	if state.StateExpired(s.now()) {
		return SocialLoginState{}, ErrStateExpired
	}
	if err := s.repo.LinkSocialProvider(ctx, state.TenantID, state.PlatformUserID, state.Provider, externalSubject); err != nil {
		return SocialLoginState{}, err
	}
	_ = s.events.Publish(ctx, "user.social_linked", state.TenantID, map[string]any{
		"user_id":  state.PlatformUserID,
		"provider": string(state.Provider),
	})
	return state, nil
}
