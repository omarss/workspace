package identity

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"net/url"

	"github.com/Nerzal/gocloak/v14"
)

// KeycloakProvider implements IdentityProvider against gocloak v14.0.3.
//
// The hashed-link URL builder (StartSocialLogin) is the most security-
// sensitive method here — it deliberately does NOT call into Keycloak.
// We construct the URL the user's browser must visit; Keycloak then runs
// the OAuth dance with the external IdP. See ADR 014 for rationale.
type KeycloakProvider struct {
	kc      *gocloak.GoCloak
	baseURL string
	tokenF  TokenFetcher
}

// TokenFetcher returns a Keycloak service-account access token. The
// implementation is responsible for caching + refreshing; the adapter calls
// it once per Keycloak request.
type TokenFetcher func(ctx context.Context) (string, error)

// NewKeycloakProvider wires the adapter. baseURL is the Keycloak server
// base URL (e.g. "http://keycloak:8080"); tokenFetcher returns an admin
// token via gocloak.LoginClient (foundations §8 anti-pattern: never
// LoginAdmin in production).
func NewKeycloakProvider(baseURL string, tokenFetcher TokenFetcher) *KeycloakProvider {
	return &KeycloakProvider{
		kc:      gocloak.NewClient(baseURL),
		baseURL: baseURL,
		tokenF:  tokenFetcher,
	}
}

// CreateUser mirrors the platform user into Keycloak. The platform user's
// id goes into the `platform_user_id` attribute so reverse lookups work
// without a separate join table.
//
// CRITICAL: tenant_id is set on the KC attribute for diagnostic use only.
// The authoritative tenant comes from the JWT, never from the attribute
// (Phase 5 plan anti-patterns).
func (k *KeycloakProvider) CreateUser(ctx context.Context, realm string, u User) (string, error) {
	tok, err := k.tokenF(ctx)
	if err != nil {
		return "", err
	}
	id, err := k.kc.CreateUser(ctx, tok, realm, gocloak.User{
		Username:      gocloak.StringP(u.ID),
		Email:         gocloak.StringP(u.Email),
		Enabled:       gocloak.BoolP(true),
		EmailVerified: gocloak.BoolP(false),
		Attributes: map[string][]string{
			"platform_user_id": {u.ID},
			"tenant_id":        {u.TenantID},
		},
	})
	if err != nil {
		return "", fmt.Errorf("gocloak create user: %w", err)
	}
	return id, nil
}

// UpdateUser pushes mutable PII to Keycloak. The platform DB is the
// source of truth for the envelope-encrypted fields; Keycloak only stores
// them so its email transport (verify-email, reset-password) works.
func (k *KeycloakProvider) UpdateUser(ctx context.Context, realm, kcUserID, email, name string) error {
	tok, err := k.tokenF(ctx)
	if err != nil {
		return err
	}
	updateUser := gocloak.User{ID: gocloak.StringP(kcUserID)}
	if email != "" {
		updateUser.Email = gocloak.StringP(email)
	}
	if name != "" {
		updateUser.FirstName = gocloak.StringP(name)
	}
	if err := k.kc.UpdateUser(ctx, tok, realm, updateUser); err != nil {
		return fmt.Errorf("gocloak update user: %w", err)
	}
	return nil
}

// SetEnabled flips the Keycloak enabled flag.
func (k *KeycloakProvider) SetEnabled(ctx context.Context, realm, kcUserID string, enabled bool) error {
	tok, err := k.tokenF(ctx)
	if err != nil {
		return err
	}
	if err := k.kc.UpdateUser(ctx, tok, realm, gocloak.User{
		ID:      gocloak.StringP(kcUserID),
		Enabled: gocloak.BoolP(enabled),
	}); err != nil {
		return fmt.Errorf("gocloak set enabled: %w", err)
	}
	return nil
}

// TriggerPasswordReset asks Keycloak to send a UPDATE_PASSWORD action email.
func (k *KeycloakProvider) TriggerPasswordReset(ctx context.Context, realm, kcUserID string) error {
	tok, err := k.tokenF(ctx)
	if err != nil {
		return err
	}
	if err := k.kc.ExecuteActionsEmail(ctx, tok, realm, gocloak.ExecuteActionsEmail{
		UserID:  gocloak.StringP(kcUserID),
		Actions: []string{"UPDATE_PASSWORD"},
	}); err != nil {
		return fmt.Errorf("gocloak execute UPDATE_PASSWORD: %w", err)
	}
	return nil
}

// TriggerEmailVerify asks Keycloak to send a VERIFY_EMAIL action email.
func (k *KeycloakProvider) TriggerEmailVerify(ctx context.Context, realm, kcUserID string) error {
	tok, err := k.tokenF(ctx)
	if err != nil {
		return err
	}
	if err := k.kc.ExecuteActionsEmail(ctx, tok, realm, gocloak.ExecuteActionsEmail{
		UserID:  gocloak.StringP(kcUserID),
		Actions: []string{"VERIFY_EMAIL"},
	}); err != nil {
		return fmt.Errorf("gocloak execute VERIFY_EMAIL: %w", err)
	}
	return nil
}

// DeleteUser hard-deletes from Keycloak. Used as a compensating action when
// the platform DB insert fails after the KC create succeeded.
func (k *KeycloakProvider) DeleteUser(ctx context.Context, realm, kcUserID string) error {
	tok, err := k.tokenF(ctx)
	if err != nil {
		return err
	}
	if err := k.kc.DeleteUser(ctx, tok, realm, kcUserID); err != nil {
		return fmt.Errorf("gocloak delete user: %w", err)
	}
	return nil
}

// StartSocialLogin builds Keycloak's hashed link URL for client-initiated
// account linking. This is the SECURE primitive for the user-facing manual
// link flow — calling CreateUserFederatedIdentity directly is forbidden
// per ADR 014 (no proof-of-possession; enables account takeover).
//
// URL shape (verified against Keycloak server-development docs):
//
//	{base}/realms/{realm}/broker/{provider}/link
//	    ?client_id={clientID}
//	    &redirect_uri={returnTo}
//	    &nonce={nonce}
//	    &hash=base64url(sha256(nonce + session_state + issued_for + provider))
//
// The user must hold the `account.manage-account-links` role for Keycloak
// to accept the link request. session_state and issued_for come from the
// caller's access token (jwx Get("session_state", &x), Get("issued_for", &x))
// — the dataplane handler extracts these before calling the service.
//
// Returns an error rather than a half-formed URL if any required argument
// is empty — fail closed.
func (k *KeycloakProvider) StartSocialLogin(_ context.Context, args StartSocialLoginArgs) (string, error) {
	if args.Realm == "" || args.ClientID == "" || !args.Provider.Valid() ||
		args.Nonce == "" || args.SessionState == "" || args.IssuedFor == "" ||
		args.ReturnTo == "" {
		return "", errors.New("identity: StartSocialLogin requires realm, client_id, provider, nonce, session_state, issued_for, return_to")
	}
	hash := computeLinkHash(args.Nonce, args.SessionState, args.IssuedFor, args.Provider)
	v := url.Values{}
	v.Set("client_id", args.ClientID)
	v.Set("redirect_uri", args.ReturnTo)
	v.Set("nonce", args.Nonce)
	v.Set("hash", hash)
	out := fmt.Sprintf(
		"%s/realms/%s/broker/%s/link?%s",
		k.baseURL,
		url.PathEscape(args.Realm),
		url.PathEscape(string(args.Provider)),
		v.Encode(),
	)
	return out, nil
}

// computeLinkHash is the canonical Keycloak client-initiated link hash:
// base64url(sha256(nonce + session_state + issued_for + provider)).
// Exposed at package scope so the unit test can pin known inputs.
func computeLinkHash(nonce, sessionState, issuedFor string, provider Provider) string {
	sum := sha256.Sum256([]byte(nonce + sessionState + issuedFor + string(provider)))
	return base64.RawURLEncoding.EncodeToString(sum[:])
}

// ListIdentityProviderLinks returns the providers (alias strings, parsed
// back into Provider) currently linked to a Keycloak user. The MVP allowlist
// (google, github, apple) filters any unexpected providers — defensive in
// case a realm operator manually configures an extra IdP.
func (k *KeycloakProvider) ListIdentityProviderLinks(ctx context.Context, realm, kcUserID string) ([]Provider, error) {
	tok, err := k.tokenF(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := k.kc.GetUserFederatedIdentities(ctx, tok, realm, kcUserID)
	if err != nil {
		return nil, fmt.Errorf("gocloak get federated identities: %w", err)
	}
	out := make([]Provider, 0, len(rows))
	for _, r := range rows {
		if r == nil || r.IdentityProvider == nil {
			continue
		}
		p := Provider(*r.IdentityProvider)
		if p.Valid() {
			out = append(out, p)
		}
	}
	return out, nil
}

// UnlinkIdentityProvider detaches a federated identity. Safe to call
// directly — no proof-of-possession needed to remove a link.
func (k *KeycloakProvider) UnlinkIdentityProvider(ctx context.Context, realm, kcUserID string, provider Provider) error {
	tok, err := k.tokenF(ctx)
	if err != nil {
		return err
	}
	if err := k.kc.DeleteUserFederatedIdentity(ctx, tok, realm, kcUserID, string(provider)); err != nil {
		return fmt.Errorf("gocloak delete federated identity: %w", err)
	}
	return nil
}
