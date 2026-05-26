package feed

import (
	"context"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/omarss/workspace/tweets/internal/server"
	"github.com/omarss/workspace/tweets/internal/store"
)

type fakeScraper struct {
	mu       sync.Mutex
	byCount  map[server.Country][]server.Tweet
	calls    map[server.Country]int
	err      error
}

func (f *fakeScraper) Search(_ context.Context, c server.Country, _ int) ([]server.Tweet, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls[c]++
	if f.err != nil {
		return nil, f.err
	}
	return f.byCount[c], nil
}

func newDB(t *testing.T) *store.DB {
	t.Helper()
	db, err := store.Open(filepath.Join(t.TempDir(), "loop.sqlite"))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	return db
}

func TestTick_FiltersSpamAboveThreshold(t *testing.T) {
	now := time.Now().UTC()
	scraper := &fakeScraper{
		byCount: map[server.Country][]server.Tweet{
			server.CountryKSA: {
				{ID: "clean", Country: server.CountryKSA, CreatedAt: now, Text: "regular update from the ministry"},
				{ID: "spammy", Country: server.CountryKSA, CreatedAt: now,
					Text: "BUY NOW BUY NOW #crypto #moon #pumpit #100x #freelambo #defi #bullrun #yolo " +
						"https://a.com https://b.com https://c.com https://d.com @x @y @z @w @v @u @t @s"},
			},
		},
		calls: map[server.Country]int{},
	}
	db := newDB(t)
	loop := NewLoop(scraper, db, nil, Config{Interval: time.Hour, SpamThreshold: 0.5})

	loop.tick(context.Background())

	got, _ := db.Latest(context.Background(), []server.Country{server.CountryKSA}, nil, nil, time.Time{}, 10)
	if len(got) != 1 || got[0].ID != "clean" {
		t.Errorf("expected only 'clean' kept, got %v", got)
	}
}

func TestTick_ScrapeFailureDoesNotPropagate(t *testing.T) {
	scraper := &fakeScraper{
		err:   context.DeadlineExceeded,
		calls: map[server.Country]int{},
	}
	db := newDB(t)
	loop := NewLoop(scraper, db, nil, Config{Interval: time.Hour})

	// Must not panic and must not return an error (tick is fire-and-forget).
	loop.tick(context.Background())

	got, _ := db.Latest(context.Background(), []server.Country{server.CountryKSA}, nil, nil, time.Time{}, 10)
	if len(got) != 0 {
		t.Errorf("expected empty store after scrape failure, got %v", got)
	}
}

func TestTick_CallsBothCountriesPerTick(t *testing.T) {
	scraper := &fakeScraper{
		byCount: map[server.Country][]server.Tweet{},
		calls:   map[server.Country]int{},
	}
	db := newDB(t)
	loop := NewLoop(scraper, db, nil, Config{Interval: time.Hour})

	loop.tick(context.Background())
	if scraper.calls[server.CountryKSA] != 1 || scraper.calls[server.CountryEgypt] != 1 {
		t.Errorf("each country must be scraped once per tick, got %v", scraper.calls)
	}
}

func TestTick_PurgesOldRows(t *testing.T) {
	now := time.Now().UTC()
	scraper := &fakeScraper{
		byCount: map[server.Country][]server.Tweet{
			server.CountryKSA: {{ID: "fresh", Country: server.CountryKSA, CreatedAt: now, Text: "hi"}},
		},
		calls: map[server.Country]int{},
	}
	db := newDB(t)
	// Seed an old row directly so the purge has something to remove.
	_ = db.SaveBatch(context.Background(), []server.Tweet{
		{ID: "old", Country: server.CountryKSA, CreatedAt: now.Add(-100 * time.Hour), Text: "ancient"},
	})
	// Pretend it was ingested a long time ago by sleeping past the
	// retention boundary in a follow-up purge call.
	time.Sleep(40 * time.Millisecond)
	loop := NewLoop(scraper, db, nil, Config{Interval: time.Hour, Retention: 20 * time.Millisecond})
	loop.tick(context.Background())

	got, _ := db.Latest(context.Background(), []server.Country{server.CountryKSA}, nil, nil, time.Time{}, 10)
	for _, tw := range got {
		if tw.ID == "old" {
			t.Errorf("expected 'old' to be purged, still present")
		}
	}
}
