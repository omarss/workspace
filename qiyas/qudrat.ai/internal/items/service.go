package items

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/omarss/qudrat/internal/store"
)

// Domain errors. The handler maps these to HTTP statuses.
var (
	ErrItemNotFound        = errors.New("items: not found")
	ErrInvalidChoice       = errors.New("items: invalid choice key")
	ErrNotServedToUser     = errors.New("items: not served to user")
	ErrAlreadyAnswered     = errors.New("items: already answered")
	ErrNoQuestionsForQuery = errors.New("items: no unserved questions match the filter")
)

// Store is the slice of *store.Queries the items domain consumes. Defining
// it here lets tests substitute an in-memory fake without depending on pgx.
type Store interface {
	PickUnservedItemsForUser(ctx context.Context, arg store.PickUnservedItemsForUserParams) ([]store.PickUnservedItemsForUserRow, error)
	MarkItemServed(ctx context.Context, arg store.MarkItemServedParams) error
	GetItemForAttempt(ctx context.Context, id uuid.UUID) (store.Item, error)
	ListItemChoicesByID(ctx context.Context, itemID uuid.UUID) ([]store.ItemChoice, error)
	InsertAttempt(ctx context.Context, arg store.InsertAttemptParams) (store.Attempt, error)
	SummarizeMasteryByTopic(ctx context.Context, arg store.SummarizeMasteryByTopicParams) ([]store.SummarizeMasteryByTopicRow, error)
	ListRecentAttemptsForUser(ctx context.Context, arg store.ListRecentAttemptsForUserParams) ([]store.ListRecentAttemptsForUserRow, error)
}

// Service is the read/write entrypoint for the item bank.
type Service struct {
	store Store
}

// NewService wires the dependency.
func NewService(s Store) *Service {
	return &Service{store: s}
}

// QuickBoostParams narrows the practice batch.
//
// Empty filter strings translate to "any value" — exposed to the user as
// query parameters; the SQL passes them as nullable narg.
type QuickBoostParams struct {
	UserID   uuid.UUID
	Count    int
	ExamType string
	Section  string
	Topic    string
}

// QuickBoost picks Count unserved items for the user (filtered if asked),
// marks each as served, and returns them — without correct_answer or
// explanation. Practice can resume even if the user never POSTs an attempt:
// the served_items rows mean the user won't see the same item again, but
// they keep the option to re-encounter the *concept* via a sibling item.
func (s *Service) QuickBoost(ctx context.Context, p QuickBoostParams) ([]ServedItem, error) {
	if p.Count <= 0 {
		p.Count = 5
	}
	if p.Count > 50 {
		p.Count = 50 // sane upper bound; the 5-question UX cap is client-side.
	}

	rows, err := s.store.PickUnservedItemsForUser(ctx, store.PickUnservedItemsForUserParams{
		UserID:     p.UserID,
		LimitCount: safeInt32(p.Count),
		ExamType:   nullableStr(p.ExamType),
		Section:    nullableStr(p.Section),
		Topic:      nullableStr(p.Topic),
	})
	if err != nil {
		return nil, fmt.Errorf("pick: %w", err)
	}
	if len(rows) == 0 {
		return nil, ErrNoQuestionsForQuery
	}

	out := make([]ServedItem, 0, len(rows))
	for _, r := range rows {
		choices, err := s.store.ListItemChoicesByID(ctx, r.ID)
		if err != nil {
			return nil, fmt.Errorf("choices: %w", err)
		}
		// Mark served BEFORE returning. If the call after this fails the
		// user might see one fewer item but no double-serves; better than
		// the opposite.
		if err := s.store.MarkItemServed(ctx, store.MarkItemServedParams{
			UserID: p.UserID,
			ItemID: r.ID,
		}); err != nil {
			return nil, fmt.Errorf("mark served: %w", err)
		}
		out = append(out, toServedItem(r, choices))
	}
	return out, nil
}

// AttemptInput is what the client sends on POST /api/attempts.
type AttemptInput struct {
	UserID      uuid.UUID
	ItemID      uuid.UUID
	ChoiceKey   string
	TimeTakenMS int
	HintUsed    bool
	ServedAt    *time.Time // optional — server uses now() if nil
}

// AttemptResult is the payload the client sees back: correctness + the
// teaching content (correct answer, explanation, distractor rationales).
type AttemptResult struct {
	AttemptID            uuid.UUID
	Correct              bool
	CorrectAnswer        string
	Explanation          string
	DistractorRationales map[string]string
}

// SubmitAttempt records the user's answer and returns the teaching content.
//
// Verifies the item exists and is accepted, scores the choice against
// correct_answer, persists the attempt, and returns the explanation. The
// no-repeat rule is enforced upstream by served_items + ItemFilter, so we
// don't need to re-check here — but ChoiceKey is validated to be A-D.
func (s *Service) SubmitAttempt(ctx context.Context, p AttemptInput) (AttemptResult, error) {
	if !validChoice(p.ChoiceKey) {
		return AttemptResult{}, ErrInvalidChoice
	}

	item, err := s.store.GetItemForAttempt(ctx, p.ItemID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return AttemptResult{}, ErrItemNotFound
		}
		return AttemptResult{}, fmt.Errorf("get item: %w", err)
	}

	correct := p.ChoiceKey == item.CorrectAnswer
	choiceKey := p.ChoiceKey
	timeTaken := safeInt32(p.TimeTakenMS)

	att, err := s.store.InsertAttempt(ctx, store.InsertAttemptParams{
		UserID:      p.UserID,
		ItemID:      p.ItemID,
		ChoiceKey:   &choiceKey,
		Correct:     &correct,
		TimeTakenMs: &timeTaken,
		HintUsed:    p.HintUsed,
		Column7:     pgxTimestamptzPtr(p.ServedAt),
	})
	if err != nil {
		return AttemptResult{}, fmt.Errorf("insert attempt: %w", err)
	}

	choices, err := s.store.ListItemChoicesByID(ctx, item.ID)
	if err != nil {
		return AttemptResult{}, fmt.Errorf("choices: %w", err)
	}
	rationales := make(map[string]string, len(choices))
	for _, c := range choices {
		rationales[c.ChoiceKey] = c.DistractorRationale
	}

	return AttemptResult{
		AttemptID:            att.ID,
		Correct:              correct,
		CorrectAnswer:        item.CorrectAnswer,
		Explanation:          item.Explanation,
		DistractorRationales: rationales,
	}, nil
}

// MasterySummary returns the per-topic accuracy snapshot for the user,
// ordered weakest first. Drives the weakness heatmap.
func (s *Service) MasterySummary(ctx context.Context, userID uuid.UUID, limit int) ([]TopicMastery, error) {
	if limit <= 0 {
		limit = 50
	}
	rows, err := s.store.SummarizeMasteryByTopic(ctx, store.SummarizeMasteryByTopicParams{
		UserID: userID,
		Limit:  safeInt32(limit),
	})
	if err != nil {
		return nil, fmt.Errorf("summarize: %w", err)
	}
	out := make([]TopicMastery, 0, len(rows))
	for _, r := range rows {
		out = append(out, toTopicMastery(r))
	}
	return out, nil
}

// History returns the user's most recent attempts.
func (s *Service) History(ctx context.Context, userID uuid.UUID, limit int) ([]HistoryEntry, error) {
	if limit <= 0 {
		limit = 20
	}
	rows, err := s.store.ListRecentAttemptsForUser(ctx, store.ListRecentAttemptsForUserParams{
		UserID: userID,
		Limit:  safeInt32(limit),
	})
	if err != nil {
		return nil, fmt.Errorf("history: %w", err)
	}
	out := make([]HistoryEntry, 0, len(rows))
	for _, r := range rows {
		out = append(out, toHistoryEntry(r))
	}
	return out, nil
}

func validChoice(k string) bool {
	switch k {
	case "A", "B", "C", "D":
		return true
	default:
		return false
	}
}

func nullableStr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// safeInt32 clamps n into the int32 range. Used at the SQL boundary for
// limit/count parameters that originate from query strings — the clamp
// keeps gosec happy and bounds the worst-case query.
func safeInt32(n int) int32 {
	const maxInt32 = 1<<31 - 1
	switch {
	case n < 0:
		return 0
	case n > maxInt32:
		return maxInt32
	default:
		return int32(n)
	}
}

func pgxTimestamptzPtr(t *time.Time) pgtype.Timestamptz {
	if t == nil {
		return pgtype.Timestamptz{} // Valid=false → COALESCE picks now()
	}
	return pgtype.Timestamptz{Time: *t, Valid: true}
}
