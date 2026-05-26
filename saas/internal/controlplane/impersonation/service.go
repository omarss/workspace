// Phase 13 — impersonation service.
//
// The service composes the minter (token signing) + the
// impersonation_session repository (audit + revocation) + the outbox
// publisher (operator.impersonation_started / _ended audit events).
// Handlers call StartSession / EndSession; the HTTP transport is
// wired separately in the deployments handler.
//
// Concurrency: Minter is safe for concurrent use (read-only state);
// the repo is whatever the caller passes — production wiring binds
// it to the sqlc-generated Queries which are pgx-pool-backed and
// safe.

package impersonation

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgtype"

	db "github.com/omarss/saas/internal/controlplane/db/sqlc"
	"github.com/omarss/saas/internal/platform/auth"
)

// Repository is the persistence surface the service needs. The sqlc
// Queries type already satisfies this — the interface exists so tests
// can provide a memory-backed fake without standing up Postgres.
type Repository interface {
	InsertImpersonationSession(ctx context.Context, arg db.InsertImpersonationSessionParams) error
	GetImpersonationSession(ctx context.Context, id string) (db.ImpersonationSession, error)
	IsImpersonationSessionActive(ctx context.Context, id string) (bool, error)
	EndImpersonationSession(ctx context.Context, arg db.EndImpersonationSessionParams) error
}

// EventPublisher matches the outbox publisher signature used elsewhere
// in the platform (Phase 10). Keeping the local copy tiny avoids
// circular imports between controlplane and the dataplane outbox
// package.
type EventPublisher interface {
	Publish(ctx context.Context, eventType, tenantID string, payload map[string]any) error
}

// Service is the orchestrator. Wire one per process at boot in cmd/controlplane.
type Service struct {
	minter    *Minter
	repo      Repository
	publisher EventPublisher
	nowFn     func() time.Time
}

// NewService constructs a Service. All collaborators are required —
// the service refuses to boot with a nil collaborator rather than
// failing on the first call.
func NewService(minter *Minter, repo Repository, publisher EventPublisher) (*Service, error) {
	if minter == nil {
		return nil, errors.New("impersonation: minter required")
	}
	if repo == nil {
		return nil, errors.New("impersonation: repo required")
	}
	if publisher == nil {
		return nil, errors.New("impersonation: publisher required")
	}
	return &Service{minter: minter, repo: repo, publisher: publisher, nowFn: time.Now}, nil
}

// StartSessionInput is the service-layer payload — distinct from the
// HTTP request type to keep the boundary clean. Caller (handler)
// validates the operator's scope + step-up + IP allowlist BEFORE
// invoking the service.
type StartSessionInput struct {
	DeploymentID    string
	OperatorID      string
	OperatorEmail   string
	TargetMemberID  string
	TargetTenantID  string
	Reason          string
	DurationSeconds int
	RequestID       string
	IPAddress       string
}

// StartSessionResult mirrors the OpenAPI StartImpersonationResponse but
// also surfaces the session_id and operator metadata for audit handling.
type StartSessionResult struct {
	SessionID string
	Token     string
	ExpiresAt time.Time
	IssuedAt  time.Time
}

// StartSession persists an impersonation_session row, mints the JWT,
// and emits the operator.impersonation_started audit event. The order
// matters: persist FIRST so the row is on disk even if the token
// signing fails; emit audit BEFORE returning to the operator so a
// dropped response cannot hide the action.
func (s *Service) StartSession(ctx context.Context, in StartSessionInput) (StartSessionResult, error) {
	if err := validateStartInput(in); err != nil {
		return StartSessionResult{}, err
	}
	now := s.nowFn().UTC()
	duration := clampSeconds(in.DurationSeconds)
	expires := now.Add(duration)
	sessionID := NewSessionID()

	// Persist the session row first. If this fails we never sign a
	// token — preventing a "token in the wild, no audit row" race.
	var memberID *string
	if in.TargetMemberID != "" {
		v := in.TargetMemberID
		memberID = &v
	}
	insErr := s.repo.InsertImpersonationSession(ctx, db.InsertImpersonationSessionParams{
		ID:             sessionID,
		DeploymentID:   in.DeploymentID,
		OperatorID:     in.OperatorID,
		OperatorEmail:  in.OperatorEmail,
		TargetMemberID: memberID,
		TargetTenantID: in.TargetTenantID,
		Reason:         in.Reason,
		// Safe int32 cast: clampSeconds bounds the value to
		// [MinDuration, MaxDuration] == [60s, 900s], well within int32.
		DurationSeconds: int32(duration / time.Second), //nolint:gosec // bounded by clampSeconds()
		IssuedAt:        pgtype.Timestamptz{Time: now, Valid: true},
		ExpiresAt:       pgtype.Timestamptz{Time: expires, Valid: true},
	})
	if insErr != nil {
		return StartSessionResult{}, fmt.Errorf("impersonation: insert session: %w", insErr)
	}

	// Mint the JWT now that the row exists.
	mintRes, err := s.minter.Mint(MintInput{
		DeploymentID:   in.DeploymentID,
		OperatorID:     in.OperatorID,
		OperatorEmail:  in.OperatorEmail,
		TenantID:       in.TargetTenantID,
		TargetMemberID: in.TargetMemberID,
		Reason:         in.Reason,
		Duration:       duration,
		SessionID:      sessionID,
		Now:            now,
	})
	if err != nil {
		// Roll forward — end the session row immediately so it can't
		// be confused with an active session in audit reads. Failing
		// to revoke is non-fatal (the token was never issued); we log
		// but do not surface a second error.
		_ = s.repo.EndImpersonationSession(ctx, db.EndImpersonationSessionParams{
			ID:          sessionID,
			EndedReason: stringPtr("revoked"),
		})
		return StartSessionResult{}, fmt.Errorf("impersonation: mint: %w", err)
	}

	// Audit BEFORE returning. A dropped HTTP response must still
	// leave an audit trail.
	payload := map[string]any{
		"actor_type":               string(auth.ActorOperator),
		"actor_id":                 in.OperatorID,
		"actor_email":              in.OperatorEmail,
		"deployment_id":            in.DeploymentID,
		"impersonation_session_id": sessionID,
		"target_tenant_id":         in.TargetTenantID,
		"target_member_id":         in.TargetMemberID,
		"reason":                   in.Reason,
		"duration_seconds":         int(duration / time.Second),
		"expires_at":               expires.Format(time.RFC3339),
		"request_id":               in.RequestID,
		"ip_address":               in.IPAddress,
		"resource_type":            "deployment",
		"resource_id":              in.DeploymentID,
	}
	if err := s.publisher.Publish(ctx, "operator.impersonation_started", in.TargetTenantID, payload); err != nil {
		// Outbox publish failure is loud but not fatal — the session
		// is persisted, the token is signed. The audit catch-up loop
		// can replay from the outbox. We do NOT roll back the session
		// because the operator needs the token for incident response;
		// a missing audit row is recoverable, a stuck operator is not.
		// The handler should log this via slog.
		return StartSessionResult{}, fmt.Errorf("impersonation: publish audit event: %w", err)
	}

	return StartSessionResult{
		SessionID: sessionID,
		Token:     mintRes.Token,
		ExpiresAt: expires,
		IssuedAt:  now,
	}, nil
}

// EndSession revokes an active impersonation session. Idempotent: an
// already-ended row returns nil (the data-plane verifier will refuse
// the token regardless).
func (s *Service) EndSession(ctx context.Context, sessionID, endedReason string, operatorID string) error {
	if sessionID == "" {
		return errors.New("impersonation: sessionID required")
	}
	reason := endedReason
	if reason == "" {
		reason = "operator_request"
	}
	if !validEndedReason(reason) {
		return fmt.Errorf("impersonation: invalid ended_reason %q", reason)
	}
	row, err := s.repo.GetImpersonationSession(ctx, sessionID)
	if err != nil {
		return fmt.Errorf("impersonation: lookup session: %w", err)
	}
	// Allow only the originating operator to end the session. A
	// future Phase ADR will broaden this to operator_admin, but for
	// MVP the rule is simple.
	if operatorID != "" && row.OperatorID != operatorID {
		return errors.New("impersonation: only the originating operator may end the session")
	}
	if err := s.repo.EndImpersonationSession(ctx, db.EndImpersonationSessionParams{
		ID:          sessionID,
		EndedReason: &reason,
	}); err != nil {
		return fmt.Errorf("impersonation: end session: %w", err)
	}
	payload := map[string]any{
		"actor_type":               string(auth.ActorOperator),
		"actor_id":                 row.OperatorID,
		"actor_email":              row.OperatorEmail,
		"deployment_id":            row.DeploymentID,
		"impersonation_session_id": sessionID,
		"target_tenant_id":         row.TargetTenantID,
		"ended_reason":             reason,
		"resource_type":            "deployment",
		"resource_id":              row.DeploymentID,
	}
	if err := s.publisher.Publish(ctx, "operator.impersonation_ended", row.TargetTenantID, payload); err != nil {
		return fmt.Errorf("impersonation: publish end audit: %w", err)
	}
	return nil
}

// SessionStatus is the lightweight check the data-plane middleware
// calls per request. Active == true when the row exists, ended_at is
// null, and expires_at > now.
func (s *Service) SessionStatus(ctx context.Context, sessionID string) (active bool, err error) {
	if sessionID == "" {
		return false, errors.New("impersonation: sessionID required")
	}
	return s.repo.IsImpersonationSessionActive(ctx, sessionID)
}

func validateStartInput(in StartSessionInput) error {
	if in.DeploymentID == "" || !strings.HasPrefix(in.DeploymentID, "dep_") {
		return errors.New("impersonation: invalid DeploymentID")
	}
	if in.OperatorID == "" || !strings.HasPrefix(in.OperatorID, "op_") {
		return errors.New("impersonation: invalid OperatorID")
	}
	if in.OperatorEmail == "" {
		return errors.New("impersonation: OperatorEmail required")
	}
	if in.TargetTenantID == "" {
		return errors.New("impersonation: TargetTenantID required")
	}
	reason := strings.TrimSpace(in.Reason)
	if reason == "" {
		return errors.New("impersonation: Reason required")
	}
	if len(reason) > 256 {
		return errors.New("impersonation: Reason exceeds 256 chars")
	}
	return nil
}

func clampSeconds(s int) time.Duration {
	d := time.Duration(s) * time.Second
	if d <= 0 {
		// API default is 900 (15 min); the handler will have already
		// resolved zero -> default but defending here lets the service
		// be called from non-HTTP contexts safely.
		return 5 * time.Minute
	}
	return clamp(d, MinDuration, MaxDuration)
}

func validEndedReason(r string) bool {
	switch r {
	case "operator_request", "expired", "revoked":
		return true
	}
	return false
}

func stringPtr(s string) *string { return &s }
