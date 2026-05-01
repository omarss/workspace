package inference

import (
	"context"
	"errors"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/omarss/prompter/internal/store"
	"github.com/omarss/prompter/pkg/llm"
)

// mockStore implements ModelStore with hand-set fixtures.
type mockStore struct {
	all    []store.Model
	bySlug map[string]store.Model
}

func (m *mockStore) ListActiveModels(_ context.Context) ([]store.Model, error) {
	return m.all, nil
}

func (m *mockStore) GetActiveModelBySlug(_ context.Context, slug string) (store.Model, error) {
	if r, ok := m.bySlug[slug]; ok {
		return r, nil
	}
	return store.Model{}, pgx.ErrNoRows
}

// mockProvider records the request it was called with and replies with a
// fixture response.
type mockProvider struct {
	got  llm.Request
	resp llm.Response
	err  error
}

func (p *mockProvider) Chat(_ context.Context, req llm.Request) (llm.Response, error) {
	p.got = req
	return p.resp, p.err
}

func numeric(f float64) pgtype.Numeric {
	var n pgtype.Numeric
	_ = n.Scan(formatFloat(f))
	return n
}

// formatFloat avoids pulling strconv/fmt into the helper signature; the
// values we test (1.0, 2.5) are exact in float64 and round-trip safely.
func formatFloat(f float64) string {
	switch f {
	case 1.0:
		return "1.0"
	case 2.5:
		return "2.5"
	case 7.0:
		return "7.0"
	case 32.0:
		return "32.0"
	default:
		return "0.0"
	}
}

func sampleModels() []store.Model {
	return []store.Model{
		{Slug: "big", DisplayName: "Big", Provider: "together", ParamCountB: numeric(32.0), Multiplier: numeric(1.0), Active: true},
		{Slug: "tiny", DisplayName: "Tiny", Provider: "together", ParamCountB: numeric(1.0), Multiplier: numeric(7.0), Active: true},
	}
}

func newSvc(t *testing.T, prov llm.Provider) *Service {
	t.Helper()
	all := sampleModels()
	bySlug := map[string]store.Model{}
	for _, m := range all {
		bySlug[m.Slug] = m
	}
	return NewService(prov, &mockStore{all: all, bySlug: bySlug}, "be terse")
}

func TestListModels(t *testing.T) {
	t.Parallel()
	s := newSvc(t, &mockProvider{})
	got, err := s.ListModels(context.Background())
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(got) != 2 {
		t.Fatalf("len = %d, want 2", len(got))
	}
	if got[0].Multiplier != 1.0 || got[1].Multiplier != 7.0 {
		t.Fatalf("multipliers not unpacked: %+v", got)
	}
}

func TestGetModel_NotFound(t *testing.T) {
	t.Parallel()
	s := newSvc(t, &mockProvider{})
	_, err := s.GetModel(context.Background(), "missing")
	if !errors.Is(err, ErrModelNotFound) {
		t.Fatalf("err = %v, want ErrModelNotFound", err)
	}
}

func TestRun_HappyPath(t *testing.T) {
	t.Parallel()
	prov := &mockProvider{resp: llm.Response{Content: "def f(): pass", PromptTokens: 5, OutputTokens: 4}}
	s := newSvc(t, prov)

	res, err := s.Run(context.Background(), RunParams{
		ModelSlug: "tiny",
		Prompt:    "empty function",
		Seed:      42,
		MaxTokens: 256,
	})
	if err != nil {
		t.Fatalf("run: %v", err)
	}
	if res.Output != "def f(): pass" {
		t.Errorf("output = %q", res.Output)
	}
	if res.Model.Slug != "tiny" {
		t.Errorf("model.slug = %q", res.Model.Slug)
	}
	// Determinism: temperature must always be zero, the seed forwarded.
	if prov.got.Temperature != 0 {
		t.Errorf("temperature = %v, want 0", prov.got.Temperature)
	}
	if prov.got.Seed != 42 {
		t.Errorf("seed = %v", prov.got.Seed)
	}
	// System prompt is prepended when set.
	if len(prov.got.Messages) != 2 || prov.got.Messages[0].Role != llm.RoleSystem {
		t.Errorf("messages = %+v", prov.got.Messages)
	}
}

func TestRun_BadSlug(t *testing.T) {
	t.Parallel()
	s := newSvc(t, &mockProvider{})
	_, err := s.Run(context.Background(), RunParams{ModelSlug: "missing", Prompt: "x"})
	if !errors.Is(err, ErrModelNotFound) {
		t.Fatalf("err = %v, want ErrModelNotFound", err)
	}
}

func TestRun_ProviderError(t *testing.T) {
	t.Parallel()
	want := errors.New("upstream down")
	s := newSvc(t, &mockProvider{err: want})
	_, err := s.Run(context.Background(), RunParams{ModelSlug: "tiny", Prompt: "x"})
	if err == nil || !errors.Is(err, want) {
		t.Fatalf("err = %v, want wrapped %v", err, want)
	}
}
