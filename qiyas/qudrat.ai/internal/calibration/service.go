// Package calibration runs the periodic sweep that updates
// items.difficulty_calibrated from real learner accuracy.
//
// Spec §10 step 10 + §24:
//
//   - For every item with ≥ minAttempts answered, set difficulty_calibrated
//     to the avg accuracy in [0,1] (higher = easier).
//   - Items that look broken (very low accuracy with high attempts → too
//     hard; very high accuracy with high attempts → too easy) get pushed
//     back to 'needs_review' so a human can decide whether to retire.
//
// The sweep is intended to run from cmd/worker on a cron — there is no
// hot-path consumer, so per-row latency doesn't matter.
package calibration

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strconv"

	"github.com/jackc/pgx/v5/pgtype"

	"github.com/omarss/qudrat/internal/events"
	"github.com/omarss/qudrat/internal/store"
)

// Thresholds are deliberately conservative. Tightening costs items.
const (
	defaultMinAttempts       = 30
	tooHardAccuracyThreshold = 0.20
	tooEasyAccuracyThreshold = 0.95
	flagAttemptsRequired     = 50
)

// Store is the slice of *store.Queries the calibration sweep consumes.
type Store interface {
	ItemsToCalibrate(ctx context.Context, minAttempts int32) ([]store.ItemsToCalibrateRow, error)
	UpdateItemCalibratedDifficulty(ctx context.Context, arg store.UpdateItemCalibratedDifficultyParams) error
	SetItemStatus(ctx context.Context, arg store.SetItemStatusParams) error
}

// Service drives one calibration sweep at a time.
type Service struct {
	store  Store
	events *events.Service
	logger *slog.Logger
}

// NewService wires deps.
func NewService(s Store, ev *events.Service, logger *slog.Logger) *Service {
	if logger == nil {
		logger = slog.Default()
	}
	return &Service{store: s, events: ev, logger: logger}
}

// RunResult summarises a sweep.
type RunResult struct {
	Inspected int
	Updated   int
	Flagged   int
}

// Run executes a single calibration pass over every item with ≥ minAttempts
// answered. Returns counts for observability.
func (s *Service) Run(ctx context.Context, minAttempts int) (RunResult, error) {
	if minAttempts <= 0 {
		minAttempts = defaultMinAttempts
	}
	rows, err := s.store.ItemsToCalibrate(ctx, int32(minAttempts)) //nolint:gosec
	if err != nil {
		return RunResult{}, fmt.Errorf("items to calibrate: %w", err)
	}

	res := RunResult{Inspected: len(rows)}
	for _, row := range rows {
		num := numericFromFloat(row.Accuracy)
		if err := s.store.UpdateItemCalibratedDifficulty(ctx, store.UpdateItemCalibratedDifficultyParams{
			ID:                   row.ID,
			DifficultyCalibrated: num,
		}); err != nil {
			s.logger.Warn("update calibrated", "item", row.ID, "err", err)
			continue
		}
		res.Updated++

		// Flag obvious outliers for human review.
		if int(row.Attempts) < flagAttemptsRequired {
			continue
		}
		if row.Accuracy <= tooHardAccuracyThreshold || row.Accuracy >= tooEasyAccuracyThreshold {
			if err := s.store.SetItemStatus(ctx, store.SetItemStatusParams{
				ID:     row.ID,
				Status: "needs_review",
			}); err != nil {
				s.logger.Warn("flag for review", "item", row.ID, "err", err)
				continue
			}
			res.Flagged++
			id := row.ID
			s.events.Record(ctx, events.TypeItemNeedsReview, nil, &id, map[string]any{
				"reason":   "calibration_outlier",
				"accuracy": row.Accuracy,
				"attempts": row.Attempts,
			})
		}
	}
	return res, nil
}

func numericFromFloat(f float64) pgtype.Numeric {
	var n pgtype.Numeric
	if err := n.Scan(strconv.FormatFloat(f, 'f', 6, 64)); err != nil {
		return pgtype.Numeric{}
	}
	return n
}

// ErrNoItems is returned when the sweep finds nothing to calibrate (e.g.
// brand-new deploy with no attempts yet). Callers can ignore it.
var ErrNoItems = errors.New("calibration: no items meet minimum attempt threshold")
