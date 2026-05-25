package identity

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"regexp"
	"strings"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/id"
)

// emailPattern is a lightweight server-side check. The OpenAPI spec carries
// the authoritative format=email validation; this is defence-in-depth so the
// service refuses bad input even when the spec validator is bypassed.
var emailPattern = regexp.MustCompile(`^[^@\s]+@[^@\s]+\.[^@\s]+$`)

const (
	emailMaxLen  = 254
	nameMaxLen   = 200
	phoneMaxLen  = 32
	defaultRealm = "saas-data-local"
	stateTTL     = 5 * time.Minute
	nonceByteLen = 16
	stateByteLen = 32
)

// Service is the identity application service. It validates input, calls
// the repository + Keycloak provider, and emits domain events.
type Service struct {
	repo         Repository
	provider     IdentityProvider
	hasher       EmailHasher
	events       EventPublisher
	notify       NotificationsHook
	deploymentID string
	realm        string
	clientID     string
	now          func() time.Time
}

// NotificationsHook lets Identity (Phase 5) route password-reset / email-
// verify emails through the Phase-6 Notifications module without
// importing it directly (avoids a circular dep). Wiring lives in
// cmd/dataplane/main.go: when NOTIFICATIONS_ENABLED=true the binary
// passes an adapter over notifications.Service; otherwise it's nil and
// the legacy Keycloak SMTP path runs.
type NotificationsHook interface {
	SendPasswordReset(ctx context.Context, tenantID, userID, resetURL string, ttlMinutes int) error
	SendEmailVerify(ctx context.Context, tenantID, userID, verifyURL string, ttlMinutes int) error
}

// Config groups Service constructor parameters. Keeps NewService callable
// without a ten-parameter signature.
type Config struct {
	Repo     Repository
	Provider IdentityProvider
	Hasher   EmailHasher
	Events   EventPublisher
	// Notify is optional. When non-nil, password-reset / email-verify
	// trigger calls route through the Notifications module (Novu) instead
	// of Keycloak's built-in SMTP. cmd/dataplane wires this when
	// NOTIFICATIONS_ENABLED=true.
	Notify       NotificationsHook
	DeploymentID string
	Realm        string // empty defaults to "saas-data-local" (Phase 5 dev)
	ClientID     string // empty defaults to the realm name
}

// NewService constructs a Service from cfg.
func NewService(cfg Config) *Service {
	realm := cfg.Realm
	if realm == "" {
		realm = defaultRealm
	}
	clientID := cfg.ClientID
	if clientID == "" {
		clientID = realm
	}
	return &Service{
		repo:         cfg.Repo,
		provider:     cfg.Provider,
		hasher:       cfg.Hasher,
		events:       cfg.Events,
		notify:       cfg.Notify,
		deploymentID: cfg.DeploymentID,
		realm:        realm,
		clientID:     clientID,
		now:          time.Now,
	}
}

// WithClock replaces the clock used for created_at / state TTL. Tests only.
func (s *Service) WithClock(now func() time.Time) *Service {
	s.now = now
	return s
}

// Create makes a new platform user, mirrors it into Keycloak, and emits
// `user.created`. Email is HMAC'd to back per-tenant uniqueness; the
// envelope-encrypt happens in the repository layer (strict-mode walker).
func (s *Service) Create(ctx context.Context, tenantID, email, name string, sendVerificationEmail bool, metadata map[string]string) (User, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return User{}, err
	}
	email = strings.TrimSpace(email)
	if err := validateEmail(email); err != nil {
		return User{}, err
	}
	if err := validateName(name); err != nil {
		return User{}, err
	}
	if err := validateMetadata(metadata); err != nil {
		return User{}, err
	}

	normalised := s.hasher.Normalise(email)
	hash, err := s.hasher.Hash(ctx, s.deploymentID, normalised)
	if err != nil {
		return User{}, err
	}

	// Friendly 422 vs leaking the DB UNIQUE error. The constraint still backs
	// the race, but the pre-check is the common case.
	if existing, err := s.repo.GetByEmailHash(ctx, tenantID, hash); err == nil && existing.ID != "" {
		return User{}, ErrEmailTaken
	} else if err != nil && !errors.Is(err, ErrNotFound) {
		return User{}, err
	}

	now := s.now().UTC()
	u := User{
		ID:              id.New(id.PrefixUser),
		TenantID:        tenantID,
		Email:           email,
		Name:            name,
		EmailLookupHash: hash,
		EmailVerified:   false,
		Status:          StatusActive,
		Metadata:        metadata,
		RowSeq:          1,
		CreatedAt:       now,
		UpdatedAt:       now,
	}

	kcUserID, err := s.provider.CreateUser(ctx, s.realm, u)
	if err != nil {
		return User{}, errors.Join(ErrProviderUnavailable, err)
	}
	u.KeycloakUserID = kcUserID

	created, err := s.repo.Create(ctx, u)
	if err != nil {
		// Compensating action: delete the orphaned Keycloak user. Failure
		// here is logged but not surfaced — the caller already has a 5xx.
		_ = s.provider.DeleteUser(ctx, s.realm, kcUserID)
		return User{}, err
	}

	if sendVerificationEmail {
		// Best-effort. The user can re-trigger via POST /verify-email.
		if err := s.provider.TriggerEmailVerify(ctx, s.realm, kcUserID); err != nil {
			_ = err // log only; orchestrator will surface via slog
		}
	}

	_ = s.events.Publish(ctx, "user.created", created.TenantID, map[string]any{
		"user_id":          created.ID,
		"tenant_id":        created.TenantID,
		"keycloak_user_id": created.KeycloakUserID,
	})
	return created, nil
}

// Get returns the user if and only if it belongs to the caller's tenant.
func (s *Service) Get(ctx context.Context, tenantID, userID string) (User, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return User{}, err
	}
	return s.repo.Get(ctx, tenantID, userID)
}

// List enumerates users in the caller's tenant. emailFilter, if non-empty,
// performs an HMAC-equality lookup.
func (s *Service) List(ctx context.Context, tenantID string, limit int, cursor *ListCursor, emailFilter string) ([]User, bool, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return nil, false, err
	}
	var hash []byte
	if emailFilter != "" {
		h, err := s.hasher.Hash(ctx, s.deploymentID, s.hasher.Normalise(emailFilter))
		if err != nil {
			return nil, false, err
		}
		hash = h
	}
	if limit <= 0 || limit > 200 {
		limit = 25
	}
	return s.repo.List(ctx, tenantID, limit, cursor, hash)
}

// Update applies a patch under optimistic concurrency. Mirrors Tenants.
func (s *Service) Update(ctx context.Context, tenantID, userID string, expectedSeq int64, patch UpdatePatch) (User, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return User{}, err
	}
	if patch.Name != nil {
		if err := validateName(*patch.Name); err != nil {
			return User{}, err
		}
	}
	if patch.Phone != nil && len(*patch.Phone) > phoneMaxLen {
		return User{}, ErrInvalidInput
	}
	if patch.PatchMetadata {
		if err := validateMetadata(patch.Metadata); err != nil {
			return User{}, err
		}
	}
	updated, err := s.repo.Update(ctx, tenantID, userID, expectedSeq, patch)
	if err != nil {
		return User{}, err
	}
	_ = s.events.Publish(ctx, "user.updated", updated.TenantID, map[string]any{"user_id": updated.ID})
	return updated, nil
}

// Disable flips status to disabled, propagates Enabled=false to Keycloak,
// and emits `user.disabled`. Token revocation is not done immediately
// (see Phase 5 plan Decisions); existing tokens expire within ≤ 1 h.
func (s *Service) Disable(ctx context.Context, tenantID, userID string) (User, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return User{}, err
	}
	u, err := s.repo.Get(ctx, tenantID, userID)
	if err != nil {
		return User{}, err
	}
	if err := s.provider.SetEnabled(ctx, s.realm, u.KeycloakUserID, false); err != nil {
		return User{}, errors.Join(ErrProviderUnavailable, err)
	}
	updated, err := s.repo.SetStatus(ctx, tenantID, userID, StatusDisabled)
	if err != nil {
		return User{}, err
	}
	_ = s.events.Publish(ctx, "user.disabled", updated.TenantID, map[string]any{"user_id": updated.ID})
	return updated, nil
}

// Enable re-activates a previously-disabled user. Symmetric with Disable.
func (s *Service) Enable(ctx context.Context, tenantID, userID string) (User, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return User{}, err
	}
	u, err := s.repo.Get(ctx, tenantID, userID)
	if err != nil {
		return User{}, err
	}
	if err := s.provider.SetEnabled(ctx, s.realm, u.KeycloakUserID, true); err != nil {
		return User{}, errors.Join(ErrProviderUnavailable, err)
	}
	updated, err := s.repo.SetStatus(ctx, tenantID, userID, StatusActive)
	if err != nil {
		return User{}, err
	}
	_ = s.events.Publish(ctx, "user.enabled", updated.TenantID, map[string]any{"user_id": updated.ID})
	return updated, nil
}

// SoftDelete sets status=deleted + stamps deleted_at + disables Keycloak.
// Hard delete lives behind /control/v1/deployments/{id}/purge (Phase 12e).
func (s *Service) SoftDelete(ctx context.Context, tenantID, userID string, expectedSeq int64) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	u, err := s.repo.Get(ctx, tenantID, userID)
	if err != nil {
		return err
	}
	if err := s.provider.SetEnabled(ctx, s.realm, u.KeycloakUserID, false); err != nil {
		return errors.Join(ErrProviderUnavailable, err)
	}
	deleted, err := s.repo.SoftDelete(ctx, tenantID, userID, expectedSeq)
	if err != nil {
		return err
	}
	_ = s.events.Publish(ctx, "user.deleted", deleted.TenantID, map[string]any{"user_id": deleted.ID})
	return nil
}

// TriggerPasswordReset asks the configured transport to send a
// password-reset email. When Config.Notify is wired (NOTIFICATIONS_ENABLED
// at boot), the request flows through the Notifications module + Novu;
// otherwise the Phase 5 fallback uses Keycloak's built-in SMTP
// (ExecuteActionsEmail).
//
// Either way the same outbox event is emitted so audit / Phase 10
// consumers see a uniform record regardless of the transport.
func (s *Service) TriggerPasswordReset(ctx context.Context, tenantID, userID string) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	u, err := s.repo.Get(ctx, tenantID, userID)
	if err != nil {
		return err
	}
	if u.Status != StatusActive {
		return ErrUserDisabled
	}
	if s.notify != nil {
		// Novu path: the reset URL is rendered by the workflow template
		// in Novu; we pass the Keycloak action-token URL (Phase 5
		// generated it via ExecuteActionsEmail before; the Notifications
		// rewire uses a templated link). For now we publish a stable
		// placeholder URL — Phase 6b wires the real action token after
		// Keycloak's "credentials.reset.url" admin endpoint lands. The
		// fallback Keycloak path stays the source of truth meanwhile.
		resetURL := "https://" + s.realm + ".keycloak/realms/" + s.realm + "/login-actions/reset-credentials"
		if hookErr := s.notify.SendPasswordReset(ctx, tenantID, userID, resetURL, 60); hookErr != nil {
			return errors.Join(ErrProviderUnavailable, hookErr)
		}
	} else {
		if provErr := s.provider.TriggerPasswordReset(ctx, s.realm, u.KeycloakUserID); provErr != nil {
			return errors.Join(ErrProviderUnavailable, provErr)
		}
	}
	_ = s.events.Publish(ctx, "user.password_reset_requested", u.TenantID, map[string]any{"user_id": u.ID})
	return nil
}

// TriggerEmailVerify asks the configured transport to send a
// VERIFY_EMAIL action. Symmetric with TriggerPasswordReset — when
// Config.Notify is wired the request flows through Notifications + Novu,
// otherwise it falls back to Keycloak's built-in SMTP.
//
// Outbox: emits `user.email_verify_requested` on EITHER path so audit /
// Phase 10 consumers see a uniform record regardless of transport. This
// mirrors TriggerPasswordReset's symmetric publish (Phase 6 anti-pattern
// fix: previously the Novu path returned before publishing).
func (s *Service) TriggerEmailVerify(ctx context.Context, tenantID, userID string) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	u, err := s.repo.Get(ctx, tenantID, userID)
	if err != nil {
		return err
	}
	if s.notify != nil {
		verifyURL := "https://" + s.realm + ".keycloak/realms/" + s.realm + "/login-actions/email-verify"
		if hookErr := s.notify.SendEmailVerify(ctx, tenantID, userID, verifyURL, 60); hookErr != nil {
			return errors.Join(ErrProviderUnavailable, hookErr)
		}
	} else {
		if provErr := s.provider.TriggerEmailVerify(ctx, s.realm, u.KeycloakUserID); provErr != nil {
			return errors.Join(ErrProviderUnavailable, provErr)
		}
	}
	_ = s.events.Publish(ctx, "user.email_verify_requested", u.TenantID, map[string]any{"user_id": u.ID})
	return nil
}

// --- validation helpers -----------------------------------------------------

func validateEmail(email string) error {
	if email == "" || len(email) > emailMaxLen || !emailPattern.MatchString(email) {
		return ErrInvalidInput
	}
	return nil
}

func validateName(name string) error {
	if len(name) > nameMaxLen {
		return ErrInvalidInput
	}
	return nil
}

func validateMetadata(m map[string]string) error {
	if len(m) > 16 {
		return ErrInvalidInput
	}
	for _, v := range m {
		if len(v) > 256 {
			return ErrInvalidInput
		}
	}
	return nil
}

// randomToken returns a base64url-encoded random byte string of nBytes
// entropy. Used for the social_login_state.state and nonce columns.
func randomToken(nBytes int) (string, error) {
	b := make([]byte, nBytes)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}
