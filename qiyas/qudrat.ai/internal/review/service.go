// Package review owns the human-review queue for the item bank.
//
// Phase 7 scope:
//
//   - Near-dup detection at import time (importer asks IsNearDuplicate before
//     inserting; on collision, the item lands as 'needs_review' instead of
//     'accepted').
//   - Reviewer-facing endpoints: list pending, accept, reject.
//   - LLM reviewer pass: stubbed (UpdateScores) — the actual model call lands
//     when a Together-style adapter is added to pkg/llm.
//
// Out of scope (deferred): pgvector embeddings, semantic clustering,
// reviewer-prompt versioning beyond the stored string.
package review

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/omarss/qudrat/internal/store"
)

// ErrItemNotFound is returned when the reviewer references an unknown ID.
var ErrItemNotFound = errors.New("review: item not found")

// Store is the slice of *store.Queries the reviewer surface uses.
type Store interface {
	GetItemByConceptSolutionFingerprint(ctx context.Context, arg store.GetItemByConceptSolutionFingerprintParams) (store.Item, error)
	ListItemsNeedingReview(ctx context.Context, arg store.ListItemsNeedingReviewParams) ([]store.ListItemsNeedingReviewRow, error)
	CountItemsNeedingReview(ctx context.Context) (int32, error)
	SetItemStatus(ctx context.Context, arg store.SetItemStatusParams) error
	SetItemQualityScore(ctx context.Context, arg store.SetItemQualityScoreParams) error
}

// Service exposes the review API.
type Service struct {
	store Store
}

// NewService wires the dependency.
func NewService(s Store) *Service { return &Service{store: s} }

// IsNearDuplicate returns the existing accepted item with the same
// (concept_fingerprint, solution_fingerprint) pair, if any. Empty
// fingerprints don't match — the importer skips this check for items
// without authored fingerprints.
//
// Used by the importer at insert time. Callers that get a non-zero return
// should mark the new item as `needs_review` rather than `accepted`.
func (s *Service) IsNearDuplicate(ctx context.Context, conceptFingerprint, solutionFingerprint string) (*store.Item, error) {
	if conceptFingerprint == "" || solutionFingerprint == "" {
		return nil, nil
	}
	row, err := s.store.GetItemByConceptSolutionFingerprint(ctx, store.GetItemByConceptSolutionFingerprintParams{
		ConceptFingerprint:  conceptFingerprint,
		SolutionFingerprint: solutionFingerprint,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, fmt.Errorf("near-dup lookup: %w", err)
	}
	return &row, nil
}

// QueueEntry is the public list-row of the review queue.
type QueueEntry struct {
	ID                  uuid.UUID `json:"id"`
	ExamType            string    `json:"exam_type"`
	Section             string    `json:"section"`
	Subject             string    `json:"subject"`
	Topic               string    `json:"topic"`
	Skill               string    `json:"skill"`
	DifficultyTarget    string    `json:"difficulty_target"`
	QuestionArchetype   string    `json:"question_archetype"`
	QuestionText        string    `json:"question_text"`
	ConceptFingerprint  string    `json:"concept_fingerprint"`
	SolutionFingerprint string    `json:"solution_fingerprint"`
	SurfaceFingerprint  string    `json:"surface_fingerprint"`
	CreatedAt           string    `json:"created_at"`
}

// QueueResult bundles the page with the total count so the client can
// page without a second round-trip.
type QueueResult struct {
	Entries []QueueEntry `json:"entries"`
	Total   int          `json:"total"`
}

// Queue returns up to limit pending review items, paged by offset.
func (s *Service) Queue(ctx context.Context, limit, offset int) (QueueResult, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	if offset < 0 {
		offset = 0
	}
	rows, err := s.store.ListItemsNeedingReview(ctx, store.ListItemsNeedingReviewParams{
		Limit:  int32(limit),  //nolint:gosec
		Offset: int32(offset), //nolint:gosec
	})
	if err != nil {
		return QueueResult{}, fmt.Errorf("list review: %w", err)
	}
	total, err := s.store.CountItemsNeedingReview(ctx)
	if err != nil {
		return QueueResult{}, fmt.Errorf("count review: %w", err)
	}
	out := make([]QueueEntry, 0, len(rows))
	for _, r := range rows {
		out = append(out, QueueEntry{
			ID:                  r.ID,
			ExamType:            r.ExamType,
			Section:             r.Section,
			Subject:             r.Subject,
			Topic:               r.Topic,
			Skill:               r.Skill,
			DifficultyTarget:    r.DifficultyTarget,
			QuestionArchetype:   r.QuestionArchetype,
			QuestionText:        r.QuestionText,
			ConceptFingerprint:  r.ConceptFingerprint,
			SolutionFingerprint: r.SolutionFingerprint,
			SurfaceFingerprint:  r.SurfaceFingerprint,
			CreatedAt:           r.CreatedAt.Time.Format("2006-01-02T15:04:05Z07:00"),
		})
	}
	return QueueResult{Entries: out, Total: int(total)}, nil
}

// Accept transitions the item from any status to 'accepted'.
func (s *Service) Accept(ctx context.Context, itemID uuid.UUID) error {
	return s.store.SetItemStatus(ctx, store.SetItemStatusParams{ID: itemID, Status: "accepted"})
}

// Reject transitions the item to 'rejected'.
func (s *Service) Reject(ctx context.Context, itemID uuid.UUID) error {
	return s.store.SetItemStatus(ctx, store.SetItemStatusParams{ID: itemID, Status: "rejected"})
}

// Retire transitions an already-accepted item to 'retired' — used when
// calibration data (Phase 8) shows the item is broken.
func (s *Service) Retire(ctx context.Context, itemID uuid.UUID) error {
	return s.store.SetItemStatus(ctx, store.SetItemStatusParams{ID: itemID, Status: "retired"})
}

// UpdateScores writes the reviewer-LLM scores back to the item. The actual
// LLM call lives in cmd/reviewer (a future binary) and uses pkg/llm; this
// method exists so the persistence side is wired now.
func (s *Service) UpdateScores(ctx context.Context, itemID uuid.UUID, quality, novelty, ambiguity float64, promptVersion string) error {
	return s.store.SetItemQualityScore(ctx, store.SetItemQualityScoreParams{
		ID:                  itemID,
		QualityScore:        numericPtr(quality),
		NoveltyScore:        numericPtr(novelty),
		AmbiguityScore:      numericPtr(ambiguity),
		ReviewPromptVersion: optStr(promptVersion),
	})
}

func numericPtr(f float64) pgtype.Numeric {
	var n pgtype.Numeric
	_ = n.Scan(fmt.Sprintf("%.6f", f))
	return n
}

func optStr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
