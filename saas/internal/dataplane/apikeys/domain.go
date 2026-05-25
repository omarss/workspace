// Package apikeys is the Phase 9 API-keys data-plane module. It owns the
// bearer-token CRUD endpoints (AGENTS.md §8.5), the argon2id-backed
// secret storage (§18.2), the envelope-encrypted prefix-search index for
// constant-time auth (§18.7), and the rotation grace window (§8.5).
//
// Module layout follows CONVENTIONS.md §1:
//
//	domain.go         types, enums, validation
//	errors.go         sentinel domain errors
//	ports.go          Repository + EventPublisher + auxiliary ports
//	service.go        application service (validation + orchestration)
//	repo_pgx.go       pgx-backed Repository
//	secret.go         secret generation, parsing
//	argon2.go         argon2id PHC encode / decode / verify
//	prefix_indexer.go HMAC + envelope wrapping of the lookup column
//	usage_buffer.go   last_used_at coalescing (30 s flush)
//	rate_limiter.go   in-memory token bucket per key
//	verifier.go       bearer-token auth verifier consumed by middleware
//	handler.go        chi routes + RBAC retrofit
//	security_test.go  §17.3 authorization matrix
//
// ADR 008 captures the cross-cutting decisions.
package apikeys

import (
	"fmt"
	"time"
)

// Status enumerates the lifecycle states a row can occupy. A row is in
// at most one of these states at a time.
type Status string

// Status values stored verbatim in the `status` column. The CHECK
// constraint in migrations/dataplane/000007_api_keys.up.sql pins them.
const (
	// StatusActive is the only state from which a bearer authenticates
	// against the row's argon_phc (or its predecessor during grace).
	StatusActive Status = "active"
	// StatusRevoked is set by the explicit revoke verb. Immediate
	// cut-off; auth path returns 401 api-key-revoked.
	StatusRevoked Status = "revoked"
	// StatusExpired is set by the sweeper when expires_at lapses. A
	// distinct value from `revoked` so audit + dashboards can show
	// which keys were operator-revoked versus naturally aged out.
	StatusExpired Status = "expired"
)

// Environment names the deployment-mode hint embedded in the bearer
// prefix. Phase 9 only mints `live`; `test` is reserved for forward
// compatibility (per-env rate-limit + quota separation lands in v1).
type Environment string

// Environment constants.
const (
	EnvironmentLive Environment = "live"
	EnvironmentTest Environment = "test"
)

// APIKey is the in-memory representation of a row in the `api_key`
// table. Plaintext secret material is NEVER carried on this struct —
// only the argon PHC, the visible prefix, and the envelope columns of
// the prefix-lookup index.
type APIKey struct {
	ID            string
	TenantID      string
	EnvironmentID string
	Name          string

	// Prefix is the visible 11-char prefix shown in dashboards
	// (e.g. "live_AX9BC7D3"). Stored in plaintext — the argon hash is
	// what authenticates a bearer, not the prefix.
	Prefix string

	// ArgonPHC is the argon2id PHC string of the full plaintext
	// bearer (env_prefix_random concatenated, exactly as the caller
	// presents it on the Authorization header).
	ArgonPHC string

	// Predecessor* fields are populated by a rotate; cleared by the
	// sweeper or by the next rotate. The auth path tries them when
	// the current ArgonPHC mismatches AND
	// PredecessorExpiresAt > now().
	PredecessorArgonPHC  string
	PredecessorExpiresAt *time.Time

	// PrefixLookupHash is the HMAC bucket; indexed in Postgres. The
	// HMAC key lives in OpenBao KV; see prefix_indexer.go.
	PrefixLookupHash []byte
	// PrefixLookupEnvelope is the envelope-encrypted bucket. AAD
	// includes the row id so a swap to another row's envelope fails
	// the AEAD tag check (ADR 004's AAD invariant applied per-row).
	PrefixLookupEnvelope LookupEnvelope

	Scopes []string
	Status Status

	RateLimitPerMinute *int
	IPAllowlist        []string

	CreatedBy  string
	CreatedAt  time.Time
	UpdatedAt  time.Time
	ExpiresAt  *time.Time
	LastUsedAt *time.Time
	RevokedAt  *time.Time
	RotatedAt  *time.Time

	// RowSeq is the trigger-incremented sequence used to format the
	// weak ETag header.
	RowSeq int64
}

// IsRevoked reports whether the row is in the revoked state.
func (k APIKey) IsRevoked() bool { return k.Status == StatusRevoked }

// IsExpired reports whether expires_at has elapsed. Returns false when
// the column is unset (no TTL on the row).
func (k APIKey) IsExpired(now time.Time) bool {
	if k.ExpiresAt == nil {
		return false
	}
	return now.After(*k.ExpiresAt)
}

// InGrace reports whether the predecessor argon hash is still valid at
// the supplied wall clock. Returns false when no predecessor is set.
func (k APIKey) InGrace(now time.Time) bool {
	if k.PredecessorExpiresAt == nil || k.PredecessorArgonPHC == "" {
		return false
	}
	return now.Before(*k.PredecessorExpiresAt)
}

// ETag formats the row sequence as a weak ETag value compatible with
// platform/etag.Format. Centralised here so callers don't reach for the
// raw int.
func (k APIKey) ETag() string {
	return fmt.Sprintf("W/\"v%d\"", k.RowSeq)
}

// LookupEnvelope mirrors crypto.Envelope but lives in the apikeys
// package so the repository can persist the columns without importing
// platform/crypto throughout. The walker in prefix_indexer.go translates
// to / from crypto.Envelope at the boundary.
type LookupEnvelope struct {
	Ciphertext []byte
	WrappedDEK string
	Nonce      []byte
	KID        string
	KeyVersion int
}

// IsZero reports whether the envelope carries no encrypted payload.
func (e LookupEnvelope) IsZero() bool {
	return e.WrappedDEK == "" && len(e.Ciphertext) == 0
}

// CreateInput is the application-level input to Service.Create. The
// handler builds it from the OpenAPI-generated request struct so domain
// validation lives in one place.
type CreateInput struct {
	Name               string
	Scopes             []string
	EnvironmentID      string
	ExpiresAt          *time.Time
	RateLimitPerMinute *int
	IPAllowlist        []string
	Environment        Environment // defaults to EnvironmentLive
}

// UpdatePatch lists the mutable fields. Nil pointer = leave unchanged.
// Non-nil pointer = set to the dereferenced value (set-replace
// semantics).
type UpdatePatch struct {
	Name               *string
	Scopes             *[]string
	RateLimitPerMinute *int
	IPAllowlist        *[]string
	ExpiresAt          *time.Time
}

// Constants pinning the wire-level format.
const (
	// PrefixRandomLen is the number of Crockford base32 characters in
	// the prefix-random portion (5 bytes → 8 chars). Matches the
	// `prefix` column shape: env(4) + "_" + this(8).
	PrefixRandomLen = 8
	// SecretRandomLen is the number of Crockford base32 chars in the
	// random portion (20 bytes → 32 chars). The full bearer is thus
	// env(4) + "_" + prefix(8) + "_" + this(32) = 47 chars.
	SecretRandomLen = 32

	// NameMaxLen mirrors the OpenAPI schema bound for `name`.
	NameMaxLen = 64

	// GracePeriodDefault is the default rotation grace window in
	// seconds (24 h per AGENTS.md §8.5).
	GracePeriodDefault = 86400
	// GracePeriodMax is the upper bound (7 d per AGENTS.md §8.5).
	GracePeriodMax = 604800
)
