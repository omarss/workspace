// Package inference is the application-level boundary between the OTP-
// authenticated submission flow and an LLM provider. It owns:
//
//   - the model registry (fed from `models` rows seeded by 0002_seed_models)
//   - the prompt-to-output execution path with deterministic settings
//
// A future cache layer plugs in via the unexported call to provider.Chat;
// keep this package thin so that change is local.
package inference

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/omarss/prompter/internal/store"
	"github.com/omarss/prompter/pkg/llm"
)

// ErrModelNotFound is returned when a slug doesn't match an active model.
var ErrModelNotFound = errors.New("inference: model not found or inactive")

// ModelStore is the slice of *store.Queries this package needs.
type ModelStore interface {
	ListActiveModels(ctx context.Context) ([]store.Model, error)
	GetActiveModelBySlug(ctx context.Context, slug string) (store.Model, error)
}

// Model is the cleaned-up view of a row in `models`. We don't return
// store.Model directly because callers shouldn't see pgtype.Timestamptz on
// the wire.
type Model struct {
	Slug        string  `json:"slug"`
	DisplayName string  `json:"display_name"`
	Provider    string  `json:"provider"`
	ParamCountB float64 `json:"param_count_b"`
	Multiplier  float64 `json:"multiplier"`
}

// Service runs prompts against the configured LLM provider and exposes the
// model registry to the API layer.
type Service struct {
	provider     llm.Provider
	store        ModelStore
	systemPrompt string
}

// NewService wires the dependencies. systemPrompt may be empty.
func NewService(p llm.Provider, s ModelStore, systemPrompt string) *Service {
	return &Service{provider: p, store: s, systemPrompt: systemPrompt}
}

// ListModels returns the active tier ladder.
func (s *Service) ListModels(ctx context.Context) ([]Model, error) {
	rows, err := s.store.ListActiveModels(ctx)
	if err != nil {
		return nil, fmt.Errorf("list models: %w", err)
	}
	out := make([]Model, 0, len(rows))
	for _, r := range rows {
		out = append(out, modelFromRow(r))
	}
	return out, nil
}

// GetModel returns the active model with the given slug, or ErrModelNotFound.
func (s *Service) GetModel(ctx context.Context, slug string) (Model, error) {
	row, err := s.store.GetActiveModelBySlug(ctx, slug)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Model{}, ErrModelNotFound
		}
		return Model{}, fmt.Errorf("get model: %w", err)
	}
	return modelFromRow(row), nil
}

// RunParams is what the submission worker hands to Run.
type RunParams struct {
	ModelSlug string
	Prompt    string // raw user prompt
	Seed      int64
	MaxTokens int // 0 → default (1024)
}

// RunResult is what comes back. The Model is included so the worker can
// persist the multiplier without re-querying.
type RunResult struct {
	Output       string
	PromptTokens int
	OutputTokens int
	Model        Model
}

// Run validates the slug, packs a deterministic chat request, and returns
// the provider response. Temperature is always 0 — variability would
// undermine the leaderboard.
func (s *Service) Run(ctx context.Context, p RunParams) (RunResult, error) {
	model, err := s.GetModel(ctx, p.ModelSlug)
	if err != nil {
		return RunResult{}, err
	}
	maxTokens := p.MaxTokens
	if maxTokens <= 0 {
		maxTokens = 1024
	}

	messages := make([]llm.Message, 0, 2)
	if s.systemPrompt != "" {
		messages = append(messages, llm.Message{Role: llm.RoleSystem, Content: s.systemPrompt})
	}
	messages = append(messages, llm.Message{Role: llm.RoleUser, Content: p.Prompt})

	resp, err := s.provider.Chat(ctx, llm.Request{
		Model:       model.Slug,
		Messages:    messages,
		Temperature: 0,
		Seed:        p.Seed,
		MaxTokens:   maxTokens,
	})
	if err != nil {
		return RunResult{}, fmt.Errorf("provider: %w", err)
	}
	return RunResult{
		Output:       resp.Content,
		PromptTokens: resp.PromptTokens,
		OutputTokens: resp.OutputTokens,
		Model:        model,
	}, nil
}

func modelFromRow(r store.Model) Model {
	return Model{
		Slug:        r.Slug,
		DisplayName: r.DisplayName,
		Provider:    r.Provider,
		ParamCountB: numericToFloat(r.ParamCountB),
		Multiplier:  numericToFloat(r.Multiplier),
	}
}

// numericToFloat unpacks pgtype.Numeric for json/scoring use. We tolerate
// any precision loss because the values stored (single-digit scales like
// 32.0, 1.0) round-trip cleanly through float64.
func numericToFloat(n pgtype.Numeric) float64 {
	v, err := n.Float64Value()
	if err != nil || !v.Valid {
		return 0
	}
	return v.Float64
}
