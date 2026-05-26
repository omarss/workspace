package store

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/omarss/workspace/tweets/internal/server"
)

func newTestDB(t *testing.T) *DB {
	t.Helper()
	db, err := Open(filepath.Join(t.TempDir(), "test.sqlite"))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	return db
}

func makeTweet(id, country string, createdAt time.Time, spamScore float64) server.Tweet {
	return server.Tweet{
		ID:        id,
		Author:    "Test Author",
		Handle:    "test_handle",
		Text:      "hello " + id,
		CreatedAt: createdAt,
		Country:   server.Country(country),
		SpamScore: spamScore,
	}
}

func TestSaveBatch_RoundTrip(t *testing.T) {
	db := newTestDB(t)
	ctx := context.Background()
	now := time.Now().UTC()

	tweets := []server.Tweet{
		makeTweet("a", "ksa", now.Add(-1*time.Hour), 0),
		makeTweet("b", "ksa", now.Add(-30*time.Minute), 0.2),
		makeTweet("c", "eg", now, 0),
	}
	if err := db.SaveBatch(ctx, tweets); err != nil {
		t.Fatalf("save: %v", err)
	}

	got, err := db.Latest(ctx, []server.Country{server.CountryKSA}, nil, "", time.Time{}, 10)
	if err != nil {
		t.Fatalf("latest: %v", err)
	}
	if len(got) != 2 {
		t.Fatalf("expected 2 ksa tweets, got %d", len(got))
	}
	// newest first by created_at — b was 30 min ago, a was 1 hour ago.
	if got[0].ID != "b" {
		t.Errorf("expected newest first (b), got %q", got[0].ID)
	}
	if got[1].ID != "a" {
		t.Errorf("expected oldest second (a), got %q", got[1].ID)
	}
}

func TestSaveBatch_Upsert(t *testing.T) {
	db := newTestDB(t)
	ctx := context.Background()
	now := time.Now().UTC()

	tw := makeTweet("dup", "ksa", now, 0.1)
	if err := db.SaveBatch(ctx, []server.Tweet{tw}); err != nil {
		t.Fatalf("first save: %v", err)
	}
	// Same ID, different spam score + later created_at — must replace,
	// not duplicate. Otherwise the rescraper would balloon the table.
	tw.SpamScore = 0.5
	tw.CreatedAt = now.Add(5 * time.Minute)
	if err := db.SaveBatch(ctx, []server.Tweet{tw}); err != nil {
		t.Fatalf("second save: %v", err)
	}
	got, _ := db.Latest(ctx, []server.Country{server.CountryKSA}, nil, "", time.Time{}, 10)
	if len(got) != 1 {
		t.Fatalf("expected 1 row after upsert, got %d", len(got))
	}
	if got[0].SpamScore != 0.5 {
		t.Errorf("expected updated spam_score=0.5, got %.3f", got[0].SpamScore)
	}
}

func TestLatest_PerCountryIsolation(t *testing.T) {
	db := newTestDB(t)
	ctx := context.Background()
	now := time.Now().UTC()

	_ = db.SaveBatch(ctx, []server.Tweet{
		makeTweet("k1", "ksa", now, 0),
		makeTweet("e1", "eg", now, 0),
	})
	ksa, _ := db.Latest(ctx, []server.Country{server.CountryKSA}, nil, "", time.Time{}, 10)
	eg, _ := db.Latest(ctx, []server.Country{server.CountryEgypt}, nil, "", time.Time{}, 10)

	if len(ksa) != 1 || ksa[0].ID != "k1" {
		t.Errorf("ksa query returned wrong rows: %v", ksa)
	}
	if len(eg) != 1 || eg[0].ID != "e1" {
		t.Errorf("eg query returned wrong rows: %v", eg)
	}
}

func TestLatest_DefaultLimitWhenZero(t *testing.T) {
	db := newTestDB(t)
	ctx := context.Background()
	got, err := db.Latest(ctx, []server.Country{server.CountryKSA}, nil, "", time.Time{}, 0)
	if err != nil {
		t.Fatalf("latest: %v", err)
	}
	// Empty store → empty result, but no error. Doc-driving the
	// contract via test rather than relying on the SQL alone.
	if len(got) != 0 {
		t.Errorf("expected empty, got %d", len(got))
	}
}

func TestPurgeOlderThan(t *testing.T) {
	db := newTestDB(t)
	ctx := context.Background()
	now := time.Now().UTC()

	// Insert with two distinct ingested_at values — the store stamps
	// ingested_at to time.Now() inside SaveBatch, so we approximate by
	// inserting an "old" batch, sleeping, then inserting "new".
	_ = db.SaveBatch(ctx, []server.Tweet{makeTweet("old", "ksa", now.Add(-2*time.Hour), 0)})
	time.Sleep(20 * time.Millisecond)
	cutoff := time.Now().UTC()
	time.Sleep(20 * time.Millisecond)
	_ = db.SaveBatch(ctx, []server.Tweet{makeTweet("new", "ksa", now, 0)})

	n, err := db.PurgeOlderThan(ctx, cutoff)
	if err != nil {
		t.Fatalf("purge: %v", err)
	}
	if n != 1 {
		t.Errorf("expected 1 row purged, got %d", n)
	}
	remaining, _ := db.Latest(ctx, []server.Country{server.CountryKSA}, nil, "", time.Time{}, 10)
	if len(remaining) != 1 || remaining[0].ID != "new" {
		t.Errorf("expected only 'new' to survive, got %v", remaining)
	}
}
