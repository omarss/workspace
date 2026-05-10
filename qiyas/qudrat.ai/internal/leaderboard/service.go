// Package leaderboard owns the opt-in safe-leaderboard surface.
//
// Spec §22 rules drive the design:
//
//   - Opt-in only. The /me/leaderboard endpoint flips users.leaderboard_opt_in;
//     no auto-enrolment.
//   - Nickname only. The phone number is never selected; the column is not
//     even in the row type.
//   - Min sample size. Every leaderboard requires `min_attempts` to filter
//     out single-data-point rankings.
//   - Multiple ranks. Mastery + Improvement live side by side so users have
//     more than one path to "winning" (spec §22 rule 5).
package leaderboard

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/omarss/qudrat/internal/store"
)

// Store is the slice of *store.Queries the leaderboard reads/writes.
type Store interface {
	SetLeaderboardOptIn(ctx context.Context, arg store.SetLeaderboardOptInParams) error
	SetUserNickname(ctx context.Context, arg store.SetUserNicknameParams) error
	MasteryLeaderboard(ctx context.Context, arg store.MasteryLeaderboardParams) ([]store.MasteryLeaderboardRow, error)
	ImprovementLeaderboard(ctx context.Context, arg store.ImprovementLeaderboardParams) ([]store.ImprovementLeaderboardRow, error)
}

// Service exposes the leaderboard read/write API.
type Service struct {
	store Store
}

// NewService wires the store dependency.
func NewService(s Store) *Service { return &Service{store: s} }

// SetOptIn flips the user's leaderboard_opt_in flag.
func (s *Service) SetOptIn(ctx context.Context, userID uuid.UUID, optIn bool) error {
	return s.store.SetLeaderboardOptIn(ctx, store.SetLeaderboardOptInParams{
		ID:               userID,
		LeaderboardOptIn: optIn,
	})
}

// SetNickname updates the user's display name. Empty strings are allowed —
// the leaderboard query falls back to a placeholder when the column is empty.
func (s *Service) SetNickname(ctx context.Context, userID uuid.UUID, nickname string) error {
	if len(nickname) > 64 {
		nickname = nickname[:64]
	}
	return s.store.SetUserNickname(ctx, store.SetUserNicknameParams{
		ID:       userID,
		Nickname: nickname,
	})
}

// MasteryEntry is the public row of the mastery leaderboard.
type MasteryEntry struct {
	UserID   uuid.UUID `json:"user_id"`
	Nickname string    `json:"nickname"`
	Attempts int       `json:"attempts"`
	Accuracy float64   `json:"accuracy"`
}

// Mastery returns the top-N opted-in users ranked by accuracy. Optional
// exam-type filter narrows to a single track ('qudurat', 'tahsili', etc.).
func (s *Service) Mastery(ctx context.Context, examType string, minAttempts, limit int) ([]MasteryEntry, error) {
	rows, err := s.store.MasteryLeaderboard(ctx, store.MasteryLeaderboardParams{
		ExamType:    nullableStr(examType),
		MinAttempts: clampMin(minAttempts, 10),
		LimitCount:  clampLimit(limit, 50),
	})
	if err != nil {
		return nil, fmt.Errorf("mastery: %w", err)
	}
	out := make([]MasteryEntry, 0, len(rows))
	for _, r := range rows {
		out = append(out, MasteryEntry{
			UserID:   r.ID,
			Nickname: r.Nickname,
			Attempts: int(r.Attempts),
			Accuracy: r.Accuracy,
		})
	}
	return out, nil
}

// ImprovementEntry is the public row of the week-over-week improvement leaderboard.
type ImprovementEntry struct {
	UserID           uuid.UUID `json:"user_id"`
	Nickname         string    `json:"nickname"`
	AttemptsThisWeek int       `json:"attempts_this_week"`
	ThisWeekAccuracy float64   `json:"this_week_accuracy"`
	LastWeekAccuracy float64   `json:"last_week_accuracy"`
	Improvement      float64   `json:"improvement"`
}

// Improvement returns the top-N opted-in users ranked by week-over-week
// accuracy delta — a "growth" leaderboard intended to be safer than raw
// score (spec §22 rule 5).
func (s *Service) Improvement(ctx context.Context, minAttempts, limit int) ([]ImprovementEntry, error) {
	rows, err := s.store.ImprovementLeaderboard(ctx, store.ImprovementLeaderboardParams{
		MinAttempts: clampMin(minAttempts, 10),
		LimitCount:  clampLimit(limit, 50),
	})
	if err != nil {
		return nil, fmt.Errorf("improvement: %w", err)
	}
	out := make([]ImprovementEntry, 0, len(rows))
	for _, r := range rows {
		out = append(out, ImprovementEntry{
			UserID:           r.ID,
			Nickname:         r.Nickname,
			AttemptsThisWeek: int(r.AttemptsThisWeek),
			ThisWeekAccuracy: r.ThisWeekAccuracy,
			LastWeekAccuracy: r.LastWeekAccuracy,
			Improvement:      r.ThisWeekAccuracy - r.LastWeekAccuracy,
		})
	}
	return out, nil
}

func nullableStr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func clampMin(n, fallback int) int32 {
	if n <= 0 {
		n = fallback
	}
	if n > 1000 {
		n = 1000
	}
	return int32(n) //nolint:gosec // bounds-checked above
}

func clampLimit(n, fallback int) int32 {
	if n <= 0 {
		n = fallback
	}
	if n > 200 {
		n = 200
	}
	return int32(n) //nolint:gosec // bounds-checked above
}
