// Package billing tracks subscription state and enforces the trial quota.
//
// Phase 9 scope:
//
//   - Lazy trial issuance: GetEntitlements creates a row on first access so
//     the rest of the codebase doesn't need to special-case "user has no
//     subscription yet".
//   - Daily quota check: trial users get DefaultTrialDailyAttempts answered
//     attempts per day; above that the items handler returns 402.
//   - Subscription view: /api/me/subscription exposes status + remaining
//     quota.
//
// Out of scope (deferred): payment provider integration (Stripe / Moyasar),
// webhook handlers, plan catalog, proration. The persistence side is
// already wired so adding those layers later is purely additive.
package billing

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/omarss/qudrat/internal/store"
)

// DefaultTrialDailyAttempts caps free-tier consumption. Pick a number that
// lets a serious learner sample the product (~3 sessions × 5 questions)
// without burning paid features. Configurable via env later.
const DefaultTrialDailyAttempts = 25

// ErrQuotaExceeded means the user has hit the trial daily cap and needs
// to subscribe before more attempts are allowed.
var ErrQuotaExceeded = errors.New("billing: trial daily quota exceeded")

// Store is the slice of *store.Queries the billing service consumes.
type Store interface {
	CreateTrialSubscription(ctx context.Context, userID uuid.UUID) (store.Subscription, error)
	GetCurrentSubscription(ctx context.Context, userID uuid.UUID) (store.Subscription, error)
	CancelSubscription(ctx context.Context, id uuid.UUID) error
	CountAttemptsToday(ctx context.Context, userID uuid.UUID) (int32, error)
}

// Service is the billing entrypoint.
type Service struct {
	store              Store
	trialDailyAttempts int
}

// NewService wires the dependency. trialDailyAttempts<=0 falls back to
// DefaultTrialDailyAttempts.
func NewService(s Store, trialDailyAttempts int) *Service {
	if trialDailyAttempts <= 0 {
		trialDailyAttempts = DefaultTrialDailyAttempts
	}
	return &Service{store: s, trialDailyAttempts: trialDailyAttempts}
}

// Entitlements captures everything the UI / quota gate needs to know
// about the user's plan in one struct.
type Entitlements struct {
	SubscriptionID uuid.UUID  `json:"subscription_id"`
	Plan           string     `json:"plan"`
	Status         string     `json:"status"`
	IsPaid         bool       `json:"is_paid"`
	DailyLimit     int        `json:"daily_limit,omitempty"`
	UsedToday      int        `json:"used_today"`
	Remaining      int        `json:"remaining,omitempty"`
	ExpiresAt      *time.Time `json:"expires_at,omitempty"`
}

// GetEntitlements returns the current view + lazily creates a trial row
// for users who have never had one.
func (s *Service) GetEntitlements(ctx context.Context, userID uuid.UUID) (Entitlements, error) {
	sub, err := s.currentOrCreateTrial(ctx, userID)
	if err != nil {
		return Entitlements{}, err
	}
	used, err := s.store.CountAttemptsToday(ctx, userID)
	if err != nil {
		return Entitlements{}, fmt.Errorf("count attempts today: %w", err)
	}
	out := Entitlements{
		SubscriptionID: sub.ID,
		Plan:           sub.Plan,
		Status:         sub.Status,
		IsPaid:         sub.Status == "active",
		UsedToday:      int(used),
	}
	if !out.IsPaid {
		out.DailyLimit = s.trialDailyAttempts
		out.Remaining = max(0, s.trialDailyAttempts-int(used))
	}
	if sub.ExpiresAt.Valid {
		t := sub.ExpiresAt.Time
		out.ExpiresAt = &t
	}
	return out, nil
}

// CheckAttemptQuota returns nil if the user can answer one more question
// today; ErrQuotaExceeded otherwise. Items handler calls this before
// inserting a new attempt.
func (s *Service) CheckAttemptQuota(ctx context.Context, userID uuid.UUID) error {
	ent, err := s.GetEntitlements(ctx, userID)
	if err != nil {
		return err
	}
	if ent.IsPaid {
		return nil
	}
	if ent.UsedToday >= ent.DailyLimit {
		return ErrQuotaExceeded
	}
	return nil
}

// Cancel marks the user's current subscription cancelled. No-op if there
// isn't one.
func (s *Service) Cancel(ctx context.Context, userID uuid.UUID) error {
	sub, err := s.store.GetCurrentSubscription(ctx, userID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil
		}
		return fmt.Errorf("get sub: %w", err)
	}
	if err := s.store.CancelSubscription(ctx, sub.ID); err != nil {
		return fmt.Errorf("cancel: %w", err)
	}
	return nil
}

func (s *Service) currentOrCreateTrial(ctx context.Context, userID uuid.UUID) (store.Subscription, error) {
	sub, err := s.store.GetCurrentSubscription(ctx, userID)
	if err == nil {
		return sub, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return store.Subscription{}, fmt.Errorf("get current: %w", err)
	}
	// Lazy issuance — first time we touch a brand-new account.
	sub, err = s.store.CreateTrialSubscription(ctx, userID)
	if err != nil {
		return store.Subscription{}, fmt.Errorf("create trial: %w", err)
	}
	return sub, nil
}
