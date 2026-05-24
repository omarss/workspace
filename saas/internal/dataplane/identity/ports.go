package identity

import (
	"context"
	"time"
)

// Repository abstracts persistence so the service can be unit-tested without
// a real Postgres. The pgx implementation lives in repo_pgx.go.
type Repository interface {
	Create(ctx context.Context, u User) (User, error)
	Get(ctx context.Context, tenantID, userID string) (User, error)
	GetByEmailHash(ctx context.Context, tenantID string, emailHash []byte) (User, error)
	List(ctx context.Context, tenantID string, limit int, cursor *ListCursor, emailHash []byte) ([]User, bool, error)
	Update(ctx context.Context, tenantID, userID string, expectedSeq int64, patch UpdatePatch) (User, error)
	SetStatus(ctx context.Context, tenantID, userID string, status Status) (User, error)
	SetEmailVerified(ctx context.Context, tenantID, userID string, verified bool) (User, error)
	SoftDelete(ctx context.Context, tenantID, userID string, expectedSeq int64) (User, error)

	LinkSocialProvider(ctx context.Context, tenantID, userID string, provider Provider, externalSubject string) error
	UnlinkSocialProvider(ctx context.Context, tenantID, userID string, provider Provider) error
	ListSocialProviders(ctx context.Context, tenantID, userID string) ([]SocialProvider, error)

	InsertSocialLoginState(ctx context.Context, state SocialLoginState) error
	ConsumeSocialLoginState(ctx context.Context, stateToken string) (SocialLoginState, error)
}

// ListCursor is the decoded form of the opaque cursor. Repository.List uses
// (CreatedAt, ID) as a strict tuple less-than to keyset-paginate.
type ListCursor struct {
	CreatedAt time.Time
	ID        string
}

// IdentityProvider abstracts Keycloak. The gocloak v14 adapter implements it.
// Methods follow the Keycloak admin-API verbs; the StartSocialLogin call is
// the hashed-link URL builder (ADR 014) — it does NOT call into Keycloak,
// because the user-facing manual-link flow runs entirely through the browser.
type IdentityProvider interface {
	CreateUser(ctx context.Context, realm string, u User) (kcUserID string, err error)
	UpdateUser(ctx context.Context, realm string, kcUserID, email, name string) error
	SetEnabled(ctx context.Context, realm, kcUserID string, enabled bool) error
	TriggerPasswordReset(ctx context.Context, realm, kcUserID string) error
	TriggerEmailVerify(ctx context.Context, realm, kcUserID string) error
	DeleteUser(ctx context.Context, realm, kcUserID string) error

	// StartSocialLogin builds Keycloak's hashed link URL for client-initiated
	// account linking. Caller redirects the user's browser to the returned URL.
	// Keycloak completes the OAuth dance with the external IdP and writes the
	// federated_identity row itself. See ADR 014 + Phase 5 plan §5.5.
	StartSocialLogin(ctx context.Context, args StartSocialLoginArgs) (authorizationURL string, err error)

	// ListIdentityProviderLinks returns the providers (alias strings) linked
	// to a Keycloak user. Wraps gocloak.GetUserFederatedIdentities.
	ListIdentityProviderLinks(ctx context.Context, realm, kcUserID string) ([]Provider, error)

	// UnlinkIdentityProvider detaches a federated identity. Safe to call
	// directly because detach has no proof-of-possession requirement.
	UnlinkIdentityProvider(ctx context.Context, realm, kcUserID string, provider Provider) error
}

// StartSocialLoginArgs gathers the parameters Keycloak's hashed link URL
// needs. Authoritative naming mirrors Keycloak's docs:
// nonce, session_state, issued_for. See Phase 5 plan §5.5 + ADR 014.
type StartSocialLoginArgs struct {
	Realm        string
	ClientID     string
	Provider     Provider
	Nonce        string
	SessionState string
	IssuedFor    string
	ReturnTo     string
}

// EmailHasher computes the HMAC-SHA256 lookup hash for an email. The HMAC
// key is per-Deployment, stored in OpenBao KV at
// secret/data/<deployment_id>/identity/email_hmac_key.
type EmailHasher interface {
	Normalise(email string) string
	Hash(ctx context.Context, deploymentID, email string) ([]byte, error)
}

// EventPublisher is the outbox port. Implementations write to outbox_event
// in the same transaction as the state change (CONVENTIONS.md §9).
type EventPublisher interface {
	Publish(ctx context.Context, eventType, tenantID string, payload map[string]any) error
}
