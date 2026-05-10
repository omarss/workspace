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
	PickWeakestSkillForUser(ctx context.Context, arg store.PickWeakestSkillForUserParams) (store.PickWeakestSkillForUserRow, error)
	PickMistakeClinicItems(ctx context.Context, arg store.PickMistakeClinicItemsParams) ([]store.PickMistakeClinicItemsRow, error)
	MarkItemServed(ctx context.Context, arg store.MarkItemServedParams) error
	GetItemForAttempt(ctx context.Context, id uuid.UUID) (store.Item, error)
	ListItemChoicesByID(ctx context.Context, itemID uuid.UUID) ([]store.ItemChoice, error)
	InsertAttempt(ctx context.Context, arg store.InsertAttemptParams) (store.Attempt, error)
	SummarizeMasteryByTopic(ctx context.Context, arg store.SummarizeMasteryByTopicParams) ([]store.SummarizeMasteryByTopicRow, error)
	ListRecentAttemptsForUser(ctx context.Context, arg store.ListRecentAttemptsForUserParams) ([]store.ListRecentAttemptsForUserRow, error)
}

// QuotaChecker is a hook the billing service plugs into. It returns
// billing.ErrQuotaExceeded when the user has hit the trial daily cap.
// Items uses an interface so it doesn't import internal/billing — keeps
// the dependency direction clean.
type QuotaChecker interface {
	CheckAttemptQuota(ctx context.Context, userID uuid.UUID) error
}

// Service is the read/write entrypoint for the item bank.
type Service struct {
	store Store
	quota QuotaChecker // nullable; nil means "no quota enforcement"
}

// NewService wires the store dependency. Use WithQuota to attach a
// billing-side gate.
func NewService(s Store) *Service {
	return &Service{store: s}
}

// WithQuota attaches a QuotaChecker that gates SubmitAttempt.
func (s *Service) WithQuota(q QuotaChecker) *Service {
	s.quota = q
	return s
}

// SessionParams is the union of filter knobs every session-type builder
// understands. Each builder sets the fields it cares about; the rest stay
// zero-valued and translate to "no filter" at the SQL boundary.
type SessionParams struct {
	UserID     uuid.UUID
	Count      int
	ExamType   string
	Section    string
	Topic      string
	Skill      string
	Difficulty string // "easy" | "medium" | "hard" | ""
}

// QuickBoost picks Count unserved items for the user (filtered if asked),
// marks each as served, and returns them — without correct_answer or
// explanation. Practice can resume even if the user never POSTs an attempt:
// the served_items rows mean the user won't see the same item again.
func (s *Service) QuickBoost(ctx context.Context, p SessionParams) ([]ServedItem, error) {
	return s.pickAndServe(ctx, p, defaultCount(p.Count, 5))
}

// BossFight serves only `hard` items. Difficulty filter overrides whatever
// the caller passed. Default count 8 (~10 min sprint).
func (s *Service) BossFight(ctx context.Context, p SessionParams) ([]ServedItem, error) {
	p.Difficulty = "hard"
	return s.pickAndServe(ctx, p, defaultCount(p.Count, 8))
}

// MixedSprint is a 15-question filtered set with no difficulty bias —
// the back-end relies on the random ordering and the writer's intended
// difficulty distribution to keep things mixed. Phase 8 calibration will
// upgrade this to weighted sampling per the user's mastery curve.
func (s *Service) MixedSprint(ctx context.Context, p SessionParams) ([]ServedItem, error) {
	p.Difficulty = "" // explicitly mixed
	return s.pickAndServe(ctx, p, defaultCount(p.Count, 15))
}

// minAttemptsForWeakSpot is the floor of attempts per skill required for
// the Weak Spot picker to consider it. Below this the accuracy estimate
// is too noisy to act on.
const minAttemptsForWeakSpot = 5

// ErrNotEnoughHistory is returned by adaptive sessions that need historical
// signal (mastery, mistake patterns) when the user is too new to provide it.
var ErrNotEnoughHistory = errors.New("items: not enough attempt history for adaptive session")

// WeakSpotDrill picks the user's weakest skill (≥ minAttemptsForWeakSpot
// attempts) and serves Count unserved items in it. Returns
// ErrNotEnoughHistory when no skill clears the floor.
func (s *Service) WeakSpotDrill(ctx context.Context, p SessionParams) ([]ServedItem, error) {
	row, err := s.store.PickWeakestSkillForUser(ctx, store.PickWeakestSkillForUserParams{
		UserID:  p.UserID,
		Column2: minAttemptsForWeakSpot,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ErrNotEnoughHistory
		}
		return nil, fmt.Errorf("weakest skill: %w", err)
	}
	p.Skill = row.Skill
	return s.pickAndServe(ctx, p, defaultCount(p.Count, 10))
}

// MistakeClinic surfaces fresh items in skills the user has recently
// gotten wrong. Same concept, different question — never the one they
// already missed. Returns ErrNotEnoughHistory when the user has zero
// recorded mistakes.
func (s *Service) MistakeClinic(ctx context.Context, p SessionParams) ([]ServedItem, error) {
	count := defaultCount(p.Count, 10)
	rows, err := s.store.PickMistakeClinicItems(ctx, store.PickMistakeClinicItemsParams{
		UserID: p.UserID,
		Limit:  safeInt32(count),
	})
	if err != nil {
		return nil, fmt.Errorf("mistake clinic pick: %w", err)
	}
	if len(rows) == 0 {
		return nil, ErrNotEnoughHistory
	}
	return s.markAndDecorate(ctx, p.UserID, mistakeRowsAsPick(rows))
}

// MockExam composes a session of `count` items (default 60) per the spec
// difficulty mix: 35% easy / 45% medium / 20% hard, scoped to the given
// exam_type/section. The split is approximate; rounding goes to medium so
// "60" yields 21+27+12 and the user always gets at least the hard slice.
func (s *Service) MockExam(ctx context.Context, p SessionParams) ([]ServedItem, error) {
	count := defaultCount(p.Count, 60)
	easy := count * 35 / 100
	hard := count * 20 / 100
	medium := count - easy - hard

	out := make([]ServedItem, 0, count)
	for _, bucket := range []struct {
		diff string
		n    int
	}{
		{"easy", easy},
		{"medium", medium},
		{"hard", hard},
	} {
		if bucket.n == 0 {
			continue
		}
		bp := p
		bp.Difficulty = bucket.diff
		bp.Count = bucket.n
		got, err := s.pickAndServe(ctx, bp, bucket.n)
		if err != nil {
			// Out of items in one bucket isn't fatal — it just yields a
			// shorter exam than requested. Other buckets still attempt.
			if errors.Is(err, ErrNoQuestionsForQuery) {
				continue
			}
			return nil, err
		}
		out = append(out, got...)
	}
	if len(out) == 0 {
		return nil, ErrNoQuestionsForQuery
	}
	return out, nil
}

// pickAndServe is the shared helper for every session builder that uses
// the multi-filter PickUnservedItemsForUser path.
func (s *Service) pickAndServe(ctx context.Context, p SessionParams, count int) ([]ServedItem, error) {
	if count <= 0 {
		count = 5
	}
	if count > 100 {
		count = 100
	}
	rows, err := s.store.PickUnservedItemsForUser(ctx, store.PickUnservedItemsForUserParams{
		UserID:           p.UserID,
		LimitCount:       safeInt32(count),
		ExamType:         nullableStr(p.ExamType),
		Section:          nullableStr(p.Section),
		Topic:            nullableStr(p.Topic),
		Skill:            nullableStr(p.Skill),
		DifficultyTarget: nullableStr(p.Difficulty),
	})
	if err != nil {
		return nil, fmt.Errorf("pick: %w", err)
	}
	if len(rows) == 0 {
		return nil, ErrNoQuestionsForQuery
	}
	return s.markAndDecorate(ctx, p.UserID, rows)
}

// markAndDecorate marks every row served and attaches choices.
func (s *Service) markAndDecorate(ctx context.Context, userID uuid.UUID, rows []store.PickUnservedItemsForUserRow) ([]ServedItem, error) {
	out := make([]ServedItem, 0, len(rows))
	for _, r := range rows {
		choices, err := s.store.ListItemChoicesByID(ctx, r.ID)
		if err != nil {
			return nil, fmt.Errorf("choices: %w", err)
		}
		if err := s.store.MarkItemServed(ctx, store.MarkItemServedParams{
			UserID: userID,
			ItemID: r.ID,
		}); err != nil {
			return nil, fmt.Errorf("mark served: %w", err)
		}
		out = append(out, toServedItem(r, choices))
	}
	return out, nil
}

// mistakeRowsAsPick converts the mistake-clinic row shape (which sqlc
// generates as a separate struct because the SQL has a CTE) into the
// shared PickUnservedItemsForUserRow shape so the same decorate path can
// fan out to it.
func mistakeRowsAsPick(in []store.PickMistakeClinicItemsRow) []store.PickUnservedItemsForUserRow {
	out := make([]store.PickUnservedItemsForUserRow, len(in))
	for i, r := range in {
		out[i] = store.PickUnservedItemsForUserRow(r)
	}
	return out
}

func defaultCount(requested, fallback int) int {
	if requested <= 0 {
		return fallback
	}
	if requested > 100 {
		return 100
	}
	return requested
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
//
// If a QuotaChecker is attached (via WithQuota), the trial daily cap is
// enforced BEFORE the item is fetched — failing fast with the billing
// error short-circuits the read load.
func (s *Service) SubmitAttempt(ctx context.Context, p AttemptInput) (AttemptResult, error) {
	if !validChoice(p.ChoiceKey) {
		return AttemptResult{}, ErrInvalidChoice
	}
	if s.quota != nil {
		if err := s.quota.CheckAttemptQuota(ctx, p.UserID); err != nil {
			return AttemptResult{}, err
		}
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
