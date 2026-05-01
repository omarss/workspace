// Package submissions owns the gameplay loop: validating a player's prompt,
// queueing it, and surfacing the persisted result. The grading worker (step 6)
// consumes queued rows, runs inference + tests, and writes scores back.
package submissions

import (
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"math"
	"math/big"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/omarss/prompter/internal/grading"
	"github.com/omarss/prompter/internal/store"
)

// Domain errors surface from Submit. Handlers map them to HTTP statuses.
var (
	ErrChallengeNotFound = errors.New("submissions: challenge not found or inactive")
	ErrModelNotFound     = errors.New("submissions: model not found or inactive")
	ErrPromptOverlap     = errors.New("submissions: prompt overlaps target")
	ErrSubmissionMissing = errors.New("submissions: not found")
	ErrPromptEmpty       = errors.New("submissions: prompt is empty")
)

// SubmissionStore captures the slice of *store.Queries the service uses.
type SubmissionStore interface {
	GetActiveChallengeByID(ctx context.Context, id uuid.UUID) (store.Challenge, error)
	GetActiveModelBySlug(ctx context.Context, slug string) (store.Model, error)

	CreateSubmission(ctx context.Context, arg store.CreateSubmissionParams) (store.Submission, error)
	RejectSubmission(ctx context.Context, arg store.RejectSubmissionParams) (store.Submission, error)
	GetSubmissionByIDForUser(ctx context.Context, arg store.GetSubmissionByIDForUserParams) (store.Submission, error)
}

// Service orchestrates submit + lookup. Worker-side flow (PickAndLock,
// MarkGraded) lives in step 6 alongside the sandbox.
type Service struct {
	store    SubmissionStore
	seedFunc func() int64
}

// NewService wires deps. seedFunc=nil falls back to a CSPRNG seed.
func NewService(s SubmissionStore, seedFunc func() int64) *Service {
	if seedFunc == nil {
		seedFunc = randomSeed
	}
	return &Service{store: s, seedFunc: seedFunc}
}

// SubmitParams is the input to Submit. Validation happens inside the service
// so handlers stay thin.
type SubmitParams struct {
	UserID      uuid.UUID
	ChallengeID uuid.UUID
	ModelSlug   string
	Prompt      string
}

// Submission is the wire view of a submission row, with float64 scores
// instead of pgtype.Numeric and a stable JSON shape.
type Submission struct {
	ID           uuid.UUID  `json:"id"`
	Status       string     `json:"status"`
	ChallengeID  uuid.UUID  `json:"challenge_id"`
	ModelSlug    string     `json:"model_slug"`
	Prompt       string     `json:"prompt"`
	PromptTokens int        `json:"prompt_tokens"`
	Output       string     `json:"output,omitempty"`
	Similarity   float64    `json:"similarity,omitempty"`
	TestsPassed  int        `json:"tests_passed,omitempty"`
	TestsTotal   int        `json:"tests_total,omitempty"`
	Multiplier   float64    `json:"multiplier,omitempty"`
	Brevity      float64    `json:"brevity,omitempty"`
	Score        float64    `json:"score,omitempty"`
	RejectReason string     `json:"reject_reason,omitempty"`
	CreatedAt    time.Time  `json:"created_at"`
	GradedAt     *time.Time `json:"graded_at,omitempty"`
}

// Submit validates the prompt and queues the submission for the worker.
// On anti-cheat hit, it persists a 'rejected' row so /me/submissions can
// audit attempts, and returns ErrPromptOverlap with the row.
func (s *Service) Submit(ctx context.Context, p SubmitParams) (Submission, error) {
	if p.Prompt == "" {
		return Submission{}, ErrPromptEmpty
	}

	challenge, err := s.store.GetActiveChallengeByID(ctx, p.ChallengeID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Submission{}, ErrChallengeNotFound
		}
		return Submission{}, fmt.Errorf("get challenge: %w", err)
	}

	if _, err := s.store.GetActiveModelBySlug(ctx, p.ModelSlug); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Submission{}, ErrModelNotFound
		}
		return Submission{}, fmt.Errorf("get model: %w", err)
	}

	tokens := approxTokens(p.Prompt)
	seed := s.seedFunc()

	if grading.IsTargetCopy(p.Prompt, challenge.TargetCode, 0, 0) {
		row, derr := s.store.RejectSubmission(ctx, store.RejectSubmissionParams{
			UserID:       p.UserID,
			ChallengeID:  p.ChallengeID,
			ModelSlug:    p.ModelSlug,
			Prompt:       p.Prompt,
			PromptTokens: clampInt32(tokens),
			RejectReason: ptr("prompt overlaps target"),
			Seed:         seed,
		})
		if derr != nil {
			return Submission{}, fmt.Errorf("reject: %w", derr)
		}
		return submissionFromRow(row), ErrPromptOverlap
	}

	row, err := s.store.CreateSubmission(ctx, store.CreateSubmissionParams{
		UserID:       p.UserID,
		ChallengeID:  p.ChallengeID,
		ModelSlug:    p.ModelSlug,
		Prompt:       p.Prompt,
		PromptTokens: clampInt32(tokens),
		Seed:         seed,
	})
	if err != nil {
		return Submission{}, fmt.Errorf("create: %w", err)
	}
	return submissionFromRow(row), nil
}

// Get returns the submission scoped to userID. Returns ErrSubmissionMissing
// if either the row doesn't exist or the user doesn't own it.
func (s *Service) Get(ctx context.Context, id, userID uuid.UUID) (Submission, error) {
	row, err := s.store.GetSubmissionByIDForUser(ctx, store.GetSubmissionByIDForUserParams{
		ID:     id,
		UserID: userID,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Submission{}, ErrSubmissionMissing
		}
		return Submission{}, fmt.Errorf("get: %w", err)
	}
	return submissionFromRow(row), nil
}

// approxTokens is a rough char/4 estimator for prompt size. The real
// PromptTokens count is overwritten by the worker after the LLM call.
func approxTokens(s string) int {
	if s == "" {
		return 0
	}
	t := len(s) / 4
	if t < 1 {
		t = 1
	}
	return t
}

// clampInt32 narrows an int to int32 with explicit bounds — keeps gosec
// happy while documenting that we're never near the limit (the column is
// only big enough to hold an absurd ~2B-token prompt).
func clampInt32(n int) int32 {
	switch {
	case n > math.MaxInt32:
		return math.MaxInt32
	case n < math.MinInt32:
		return math.MinInt32
	default:
		return int32(n)
	}
}

func ptr[T any](v T) *T { return &v }

// seedMax is the upper bound (exclusive) for randomSeed. Using
// math.MaxInt64 keeps the value in the positive int64 range so it round-
// trips through `bigint` cleanly.
var seedMax = big.NewInt(math.MaxInt64)

func randomSeed() int64 {
	n, err := rand.Int(rand.Reader, seedMax)
	if err != nil {
		// Fallback to time-based seed if crypto/rand fails — astronomically
		// unlikely on Linux. Worst case, two submissions share a seed.
		return time.Now().UnixNano()
	}
	return n.Int64()
}
