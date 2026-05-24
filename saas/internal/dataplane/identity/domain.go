// Package identity is the Phase 5 vertical slice: platform users behind a
// Keycloak façade with envelope-encrypted PII columns and social-login
// linking via Keycloak's IdP brokering. Hexagonal layout mirrors the Phase 2
// tenancy module (CONVENTIONS.md §1):
//
//	handler.go        HTTP boundary (oapi-codegen StrictServerInterface)
//	service.go        application orchestration
//	ports.go          Repository + IdentityProvider + EmailHasher + EventPublisher
//	repo_pgx.go       pgx-backed Repository implementation
//	provider_kc.go    gocloak v14 IdentityProvider adapter + hashed link URL builder
//	social.go         social link/unlink + opaque state token lifecycle
//	domain.go         User / SocialProvider / Status; PII envelope siblings declared here
//	errors.go         sentinel errors translated to HTTP problems
//
// PII handling: User declares <Field>Envelope siblings for every pii/
// sensitive-tagged column. The repo invokes crypto.EncryptPIIFieldsStrict —
// the strict-mode walker refuses to drop an envelope silently. AAD per
// CONVENTIONS.md §10.1 is deployment_id || resource_type || resource_id.
package identity

import (
	"time"

	"github.com/omarss/saas/internal/platform/crypto"
	"github.com/omarss/saas/internal/platform/etag"
)

// Status mirrors the OpenAPI User.status enum.
type Status string

// Allowed user lifecycle states.
const (
	StatusActive   Status = "active"
	StatusDisabled Status = "disabled"
	StatusDeleted  Status = "deleted"
)

// Valid reports whether s is one of the platform's allowed states.
func (s Status) Valid() bool {
	switch s {
	case StatusActive, StatusDisabled, StatusDeleted:
		return true
	}
	return false
}

// Provider enumerates the social IdPs MVP supports. Adding more requires an
// ADR per CONVENTIONS.md and Phase 5 plan anti-patterns.
type Provider string

// Allowed social providers in MVP (ADR 014).
const (
	ProviderGoogle Provider = "google"
	ProviderGitHub Provider = "github"
	ProviderApple  Provider = "apple"
)

// Valid reports whether p is one of the MVP-allowed providers.
func (p Provider) Valid() bool {
	switch p {
	case ProviderGoogle, ProviderGitHub, ProviderApple:
		return true
	}
	return false
}

// User is the in-memory representation passed between handler, service,
// repository, and outbox. The plaintext PII fields are populated only on
// the read path (after decrypt) and cleared immediately after the walker
// runs on the write path.
//
// CRITICAL: every PII/sensitive-tagged field carries a sibling
// <Field>Envelope of type crypto.Envelope. The strict-mode walker in
// internal/platform/crypto refuses to proceed without the sibling, so
// adding a new PII column to the schema MUST also add the Go sibling.
type User struct {
	ID              string
	TenantID        string
	KeycloakUserID  string
	Status          Status
	EmailVerified   bool
	EmailLookupHash []byte
	Email           string `pii:"true" sensitive:"true"`
	EmailEnvelope   crypto.Envelope
	Name            string `pii:"true"`
	NameEnvelope    crypto.Envelope
	Phone           string `pii:"true" sensitive:"true"`
	PhoneEnvelope   crypto.Envelope
	Metadata        map[string]string
	RowSeq          int64
	CreatedAt       time.Time
	UpdatedAt       time.Time
	DeletedAt       *time.Time
}

// ETag returns the platform's Weak ETag for this user.
func (u User) ETag() string { return etag.Format(u.RowSeq) }

// UpdatePatch carries optional PATCH fields for /v1/users/{id}. nil means
// "do not change this column".
type UpdatePatch struct {
	Name          *string `pii:"true"`
	NameEnvelope  crypto.Envelope
	Phone         *string `pii:"true" sensitive:"true"`
	PhoneEnvelope crypto.Envelope
	Metadata      map[string]string
	PatchMetadata bool
}

// SocialProvider is the linked-identity view exposed at /v1/users/{id}/social-providers.
type SocialProvider struct {
	Provider        Provider
	ExternalSubject string `sensitive:"true"`
	LinkedAt        time.Time
}

// SocialLoginState is the 5-minute state row that backs the link flow.
// The state field is the opaque random token the client receives; the nonce
// is the value passed into Keycloak's hashed link URL.
type SocialLoginState struct {
	State          string
	TenantID       string
	PlatformUserID string
	Provider       Provider
	ReturnTo       string
	Nonce          string
	CreatedAt      time.Time
	ExpiresAt      time.Time
	ConsumedAt     *time.Time
}

// StateExpired reports whether s.ExpiresAt is in the past relative to now.
func (s SocialLoginState) StateExpired(now time.Time) bool {
	return now.After(s.ExpiresAt)
}

// StateConsumed reports whether the state has already been used.
func (s SocialLoginState) StateConsumed() bool {
	return s.ConsumedAt != nil
}
