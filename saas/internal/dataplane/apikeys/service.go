package apikeys

import (
	"context"
	"errors"
	"fmt"
	"net"
	"strings"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/id"
)

// Service is the API-keys application service. It validates input,
// drives the argon + envelope-wrap dance, and emits outbox events that
// audit (Phase 10) consumes.
//
// CONVENTIONS.md §2 mandates the (ctx, tenantID, ...) shape for every
// tenant-bound method. AssertTenant precedes any tenant-bound read or
// write.
type Service struct {
	repo    Repository
	events  EventPublisher
	indexer *PrefixIndexer
	now     func() time.Time

	// deploymentID is captured at construction time so verifier /
	// rotate paths can build the envelope AAD without having to pass
	// it through every call site.
	deploymentID string
}

// Config groups the constructor parameters.
type Config struct {
	Repo         Repository
	Events       EventPublisher
	Indexer      *PrefixIndexer
	DeploymentID string
	Now          func() time.Time
}

// NewService constructs a Service from cfg.
func NewService(cfg Config) *Service {
	now := cfg.Now
	if now == nil {
		now = time.Now
	}
	return &Service{
		repo:         cfg.Repo,
		events:       cfg.Events,
		indexer:      cfg.Indexer,
		now:          now,
		deploymentID: cfg.DeploymentID,
	}
}

// DeploymentID returns the deployment id this service was constructed
// with. Used by the verifier wiring.
func (s *Service) DeploymentID() string { return s.deploymentID }

// Repository exposes the underlying repository for the verifier path.
// The verifier needs LookupByPrefixHash; exposing the full interface
// keeps the surface narrow without leaking the pgx-specific repo type.
func (s *Service) Repository() Repository { return s.repo }

// Indexer exposes the prefix indexer for the verifier path.
func (s *Service) Indexer() *PrefixIndexer { return s.indexer }

// CreateResult bundles the create response. Plaintext is returned to
// the caller exactly once; subsequent reads never include it.
type CreateResult struct {
	APIKey    APIKey
	Plaintext string
}

// Create mints a new bearer for tenant. CONVENTIONS.md §2 first
// non-ctx arg is tenantID.
//
// Implementation steps:
//  1. AssertTenant — defence in depth.
//  2. Validate name + scopes + ip_allowlist (CIDR shape).
//  3. NewSecret → plaintext + visible prefix.
//  4. HashSecret → argon2id PHC.
//  5. Indexer.IndexHash → HMAC bucket.
//  6. Mint ulid `apik_<26>`.
//  7. Indexer.WrapEnvelope(apiKeyID, hash) — AAD binds the row id.
//  8. repo.Create — atomic INSERT.
//  9. events.Publish("api_key.created").
//
// The plaintext is returned ONCE on this CreateResult and never
// persisted anywhere except the argon PHC.
func (s *Service) Create(ctx context.Context, tenantID string, in CreateInput) (CreateResult, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return CreateResult{}, err
	}
	if err := validateCreate(in); err != nil {
		return CreateResult{}, err
	}

	env := in.Environment
	if env == "" {
		env = EnvironmentLive
	}
	sec, err := NewSecret(env)
	if err != nil {
		return CreateResult{}, err
	}
	phc, err := HashSecret(sec.Plaintext)
	if err != nil {
		return CreateResult{}, err
	}
	hash, err := s.indexer.IndexHash(ctx, sec.Prefix)
	if err != nil {
		return CreateResult{}, err
	}
	apiKeyID := id.New(id.PrefixAPIKey)
	envWrap, err := s.indexer.WrapEnvelope(ctx, apiKeyID, hash)
	if err != nil {
		return CreateResult{}, err
	}

	row := APIKey{
		ID:                   apiKeyID,
		TenantID:             tenantID,
		EnvironmentID:        in.EnvironmentID,
		Name:                 in.Name,
		Prefix:               sec.Prefix,
		ArgonPHC:             phc,
		PrefixLookupHash:     hash,
		PrefixLookupEnvelope: envWrap,
		Scopes:               append([]string(nil), in.Scopes...),
		Status:               StatusActive,
		RateLimitPerMinute:   in.RateLimitPerMinute,
		IPAllowlist:          append([]string(nil), in.IPAllowlist...),
		CreatedBy:            callerActorID(ctx),
		CreatedAt:            s.now().UTC(),
		UpdatedAt:            s.now().UTC(),
		ExpiresAt:            in.ExpiresAt,
		RowSeq:               1,
	}
	saved, err := s.repo.Create(ctx, row)
	if err != nil {
		return CreateResult{}, err
	}

	// Outbox publish is best-effort here per ADR 009 (Phase 3 model).
	// A publish failure is logged via the caller (slog at the handler
	// boundary) but does not roll back the row — audit picks up the
	// row on the next reconciliation cycle. Phase 10 hardens this with
	// transactional outbox semantics.
	if s.events != nil {
		_ = s.events.Publish(ctx, "api_key.created", tenantID, map[string]any{
			"api_key_id": saved.ID,
			"prefix":     saved.Prefix,
			"scopes":     saved.Scopes,
			"created_by": saved.CreatedBy,
		})
	}

	return CreateResult{APIKey: saved, Plaintext: sec.Plaintext}, nil
}

// Get returns a tenant-scoped row by id.
func (s *Service) Get(ctx context.Context, tenantID, apiKeyID string) (APIKey, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return APIKey{}, err
	}
	return s.repo.Get(ctx, tenantID, apiKeyID)
}

// List returns up to `limit` rows for the tenant.
func (s *Service) List(ctx context.Context, tenantID string, limit int) ([]APIKey, bool, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return nil, false, err
	}
	if limit <= 0 || limit > 200 {
		limit = 25
	}
	return s.repo.List(ctx, tenantID, limit)
}

// Update applies the patch to the row. ETag mismatch returns
// ErrETagMismatch (412 at the handler).
func (s *Service) Update(ctx context.Context, tenantID, apiKeyID string, expectedSeq int64, patch UpdatePatch) (APIKey, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return APIKey{}, err
	}
	if patch.Name != nil && (len(*patch.Name) == 0 || len(*patch.Name) > NameMaxLen) {
		return APIKey{}, fmt.Errorf("%w: name length out of range", ErrInvalidInput)
	}
	if patch.Scopes != nil {
		for _, sc := range *patch.Scopes {
			if err := ValidateScope(sc); err != nil {
				return APIKey{}, err
			}
		}
	}
	if patch.IPAllowlist != nil {
		if err := validateCIDRs(*patch.IPAllowlist); err != nil {
			return APIKey{}, err
		}
	}
	updated, err := s.repo.Update(ctx, tenantID, apiKeyID, expectedSeq, patch)
	if err != nil {
		return APIKey{}, err
	}
	if s.events != nil {
		_ = s.events.Publish(ctx, "api_key.updated", tenantID, map[string]any{
			"api_key_id": updated.ID,
		})
	}
	return updated, nil
}

// Revoke is the soft / immediate cut-off path. CONVENTIONS.md §2
// requires the (ctx, tenantID, ...) shape.
func (s *Service) Revoke(ctx context.Context, tenantID, apiKeyID string) (APIKey, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return APIKey{}, err
	}
	row, err := s.repo.Revoke(ctx, tenantID, apiKeyID)
	if err != nil {
		return APIKey{}, err
	}
	if s.events != nil {
		_ = s.events.Publish(ctx, "api_key.revoked", tenantID, map[string]any{
			"api_key_id": row.ID,
		})
	}
	return row, nil
}

// RotateResult bundles the new plaintext + the post-rotate row.
type RotateResult struct {
	APIKey               APIKey
	Plaintext            string
	PredecessorExpiresAt time.Time
}

// Rotate mints a new bearer for an existing row, preserving the old
// argon hash in the predecessor columns until graceSeconds elapses.
// graceSeconds outside [0, GracePeriodMax] returns ErrGraceOutOfRange.
func (s *Service) Rotate(ctx context.Context, tenantID, apiKeyID string, graceSeconds int) (RotateResult, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return RotateResult{}, err
	}
	if graceSeconds < 0 || graceSeconds > GracePeriodMax {
		return RotateResult{}, ErrGraceOutOfRange
	}

	existing, err := s.repo.Get(ctx, tenantID, apiKeyID)
	if err != nil {
		return RotateResult{}, err
	}
	if existing.Status != StatusActive {
		return RotateResult{}, ErrNotRotatable
	}

	// Inherit the environment prefix of the existing row so a rotate
	// never silently migrates a live key to test (or vice versa).
	env := environmentFromPrefix(existing.Prefix)
	sec, err := NewSecret(env)
	if err != nil {
		return RotateResult{}, err
	}
	newPHC, err := HashSecret(sec.Plaintext)
	if err != nil {
		return RotateResult{}, err
	}
	newHash, err := s.indexer.IndexHash(ctx, sec.Prefix)
	if err != nil {
		return RotateResult{}, err
	}
	newEnv, err := s.indexer.WrapEnvelope(ctx, apiKeyID, newHash)
	if err != nil {
		return RotateResult{}, err
	}

	expires := s.now().Add(time.Duration(graceSeconds) * time.Second).UTC()
	rotated, err := s.repo.Rotate(ctx, tenantID, apiKeyID, newPHC, sec.Prefix, newHash, newEnv, expires)
	if err != nil {
		return RotateResult{}, err
	}

	if s.events != nil {
		_ = s.events.Publish(ctx, "api_key.rotated", tenantID, map[string]any{
			"api_key_id":           rotated.ID,
			"grace_period_seconds": graceSeconds,
		})
	}
	return RotateResult{APIKey: rotated, Plaintext: sec.Plaintext, PredecessorExpiresAt: expires}, nil
}

// SweepPredecessors clears expired predecessor PHCs. Driven by a
// goroutine in cmd/dataplane on a 1 h interval.
func (s *Service) SweepPredecessors(ctx context.Context) (int, error) {
	return s.repo.SweepExpiredPredecessors(ctx, s.now())
}

// ---------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------

func validateCreate(in CreateInput) error {
	if strings.TrimSpace(in.Name) == "" || len(in.Name) > NameMaxLen {
		return fmt.Errorf("%w: name length out of range", ErrInvalidInput)
	}
	if len(in.Scopes) == 0 {
		return fmt.Errorf("%w: at least one scope required", ErrInvalidInput)
	}
	for _, sc := range in.Scopes {
		if err := ValidateScope(sc); err != nil {
			return err
		}
	}
	if err := validateCIDRs(in.IPAllowlist); err != nil {
		return err
	}
	if in.RateLimitPerMinute != nil && *in.RateLimitPerMinute <= 0 {
		return fmt.Errorf("%w: rate_limit_per_minute must be positive", ErrInvalidInput)
	}
	return nil
}

func validateCIDRs(cidrs []string) error {
	for _, c := range cidrs {
		if c == "" {
			continue
		}
		if _, _, err := net.ParseCIDR(c); err != nil {
			return fmt.Errorf("%w: %q: %s", ErrInvalidCIDR, c, err.Error())
		}
	}
	return nil
}

func callerActorID(ctx context.Context) string {
	p, ok := auth.PrincipalFromContext(ctx)
	if !ok {
		return ""
	}
	return p.ActorID
}

// environmentFromPrefix returns the env hint from a visible prefix.
// Defaults to live when the parse fails — rotation must never silently
// fail because of a malformed legacy prefix.
func environmentFromPrefix(prefix string) Environment {
	if strings.HasPrefix(prefix, string(EnvironmentTest)+"_") {
		return EnvironmentTest
	}
	return EnvironmentLive
}

// IPAllowed reports whether remote is covered by any of the supplied
// CIDR blocks. An empty / nil allowlist means "all allowed". Exposed
// so the auth middleware can reuse the policy logic without
// reimplementing it.
func IPAllowed(remote string, allowlist []string) bool {
	if len(allowlist) == 0 {
		return true
	}
	ipStr := remote
	if host, _, err := net.SplitHostPort(remote); err == nil {
		ipStr = host
	}
	ip := net.ParseIP(ipStr)
	if ip == nil {
		return false
	}
	for _, c := range allowlist {
		_, network, err := net.ParseCIDR(c)
		if err != nil {
			continue
		}
		if network.Contains(ip) {
			return true
		}
	}
	return false
}

// ErrServiceNotWired is returned by Service methods that require the
// indexer or events publisher when the constructor was called without
// them. Tests that exercise the unauthenticated paths can omit either
// dependency, but production wiring MUST supply both — main.go fails
// loud on this branch.
var ErrServiceNotWired = errors.New("apikeys: service not wired correctly")
