// Package feed orchestrates the periodic scrape -> spam-filter ->
// SQLite-store pipeline that backs GET /tweets. The HTTP handler reads
// from the store so the phone never waits on a live scrape — at most
// it sees a feed that's ~interval minutes stale.
package feed

import (
	"context"
	"log/slog"
	"time"

	"github.com/omarss/workspace/tweets/internal/scrape"
	"github.com/omarss/workspace/tweets/internal/server"
	"github.com/omarss/workspace/tweets/internal/spam"
	"github.com/omarss/workspace/tweets/internal/store"
)

// Loop runs the periodic refresh. Each tick scrapes every supported
// country in turn, drops spam-scored tweets above the threshold, and
// upserts the rest into the store. Errors are logged but never abort
// the loop — a bad scrape just means the next tick tries again.
type Loop struct {
	scraper  scrape.Scraper
	store    *store.DB
	log      *slog.Logger
	interval time.Duration
	maxPerCountry int
	spamThreshold float64
	retention     time.Duration
}

// Config tunables for the loop. Zero values fall back to sensible
// defaults — keeps the main.go wire-up readable.
type Config struct {
	Interval        time.Duration
	MaxPerCountry   int
	SpamThreshold   float64
	Retention       time.Duration
}

func NewLoop(s scrape.Scraper, db *store.DB, log *slog.Logger, cfg Config) *Loop {
	if cfg.Interval <= 0 {
		cfg.Interval = 10 * time.Minute
	}
	if cfg.MaxPerCountry <= 0 {
		cfg.MaxPerCountry = 40
	}
	if cfg.SpamThreshold <= 0 {
		cfg.SpamThreshold = 0.7
	}
	if cfg.Retention <= 0 {
		cfg.Retention = 24 * time.Hour
	}
	if log == nil {
		log = slog.Default()
	}
	return &Loop{
		scraper:       s,
		store:         db,
		log:           log,
		interval:      cfg.Interval,
		maxPerCountry: cfg.MaxPerCountry,
		spamThreshold: cfg.SpamThreshold,
		retention:     cfg.Retention,
	}
}

// Run blocks until ctx is cancelled. Fires one tick immediately so
// fresh deployments populate the cache without waiting an interval.
func (l *Loop) Run(ctx context.Context) {
	l.tick(ctx)
	t := time.NewTicker(l.interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			l.tick(ctx)
		}
	}
}

func (l *Loop) tick(ctx context.Context) {
	for _, country := range []server.Country{server.CountryKSA, server.CountryEgypt} {
		l.refreshOne(ctx, country)
	}
	cutoff := time.Now().Add(-l.retention)
	if n, err := l.store.PurgeOlderThan(ctx, cutoff); err != nil {
		l.log.Warn("purge failed", "err", err)
	} else if n > 0 {
		l.log.Info("purged old tweets", "count", n)
	}
}

func (l *Loop) refreshOne(ctx context.Context, country server.Country) {
	tweets, err := l.scraper.Search(ctx, country, l.maxPerCountry)
	if err != nil {
		l.log.Warn("scrape failed", "country", country, "err", err)
		return
	}
	kept := make([]server.Tweet, 0, len(tweets))
	for i := range tweets {
		t := &tweets[i]
		score, _ := spam.Score(spam.Compute(t.Text, time.Time{}, 0, 0, false))
		t.SpamScore = score
		if score > l.spamThreshold {
			continue
		}
		kept = append(kept, *t)
	}
	if err := l.store.SaveBatch(ctx, kept); err != nil {
		l.log.Warn("store save failed", "country", country, "err", err)
		return
	}
	l.log.Info("refreshed",
		"country", country,
		"scraped", len(tweets),
		"kept", len(kept),
		"dropped_spam", len(tweets)-len(kept),
	)
}
