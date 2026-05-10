// Package events records spec §19 product events to the events table.
//
// Recording is fire-and-forget: callers invoke Record without an error
// path. A failed insert logs at WARN but never blocks the user-facing
// request. Background analytics jobs read from the table.
//
// The event type catalog mirrors spec §19 — keep additions there before
// adding constants here.
package events

import (
	"context"
	"encoding/json"
	"log/slog"

	"github.com/google/uuid"

	"github.com/omarss/qudrat/internal/store"
)

// Spec §19 type catalog. Values are stored verbatim in events.event_type.
const (
	// 19.1 Content Events.
	TypeItemAccepted        = "item_accepted"
	TypeItemRejected        = "item_rejected"
	TypeItemNeedsReview     = "item_needs_review"
	TypeItemDuplicateReject = "item_duplicate_rejected"
	TypeItemRetired         = "item_retired"

	// 19.2 Learner Events.
	TypeUserRegistered       = "user_registered"
	TypeOTPVerified          = "otp_verified"
	TypeQuestionServed       = "question_served"
	TypeAnswerSubmitted      = "answer_submitted"
	TypePracticeSessionStart = "practice_session_started"
	TypeLeaderboardOptIn     = "leaderboard_opt_in"
	TypeLeaderboardOptOut    = "leaderboard_opt_out"

	// 19.4 Calibration (added by Phase 8 to track its own job).
	TypeCalibrationRunStart    = "calibration_run_started"
	TypeCalibrationRunComplete = "calibration_run_completed"
)

// Recorder is the slice of *store.Queries the event log uses. Defined
// here so tests can substitute a fake.
type Recorder interface {
	RecordEvent(ctx context.Context, arg store.RecordEventParams) error
}

// Service wraps the recorder + a logger and provides a typed convenience
// method per common event shape.
type Service struct {
	store  Recorder
	logger *slog.Logger
}

// NewService returns a recorder. logger=nil falls back to slog.Default.
func NewService(s Recorder, logger *slog.Logger) *Service {
	if logger == nil {
		logger = slog.Default()
	}
	return &Service{store: s, logger: logger}
}

// Record writes a fire-and-forget event. Any insert failure is logged at
// WARN and swallowed — events are observability, not source of truth.
//
// userID and itemID are optional. payload is marshalled to JSON; nil
// becomes the empty object.
func (s *Service) Record(ctx context.Context, eventType string, userID, itemID *uuid.UUID, payload any) {
	go s.recordSync(context.WithoutCancel(ctx), eventType, userID, itemID, payload)
}

// recordSync is the in-process write — broken out so internal callers
// (calibration job) can wait for the insert if they care.
func (s *Service) recordSync(ctx context.Context, eventType string, userID, itemID *uuid.UUID, payload any) {
	var raw []byte
	if payload != nil {
		buf, err := json.Marshal(payload)
		if err != nil {
			s.logger.Warn("event marshal", "type", eventType, "err", err)
			return
		}
		raw = buf
	}
	if err := s.store.RecordEvent(ctx, store.RecordEventParams{
		EventType: eventType,
		UserID:    userID,
		ItemID:    itemID,
		Column4:   raw,
	}); err != nil {
		s.logger.Warn("event insert", "type", eventType, "err", err)
	}
}
