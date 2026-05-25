// Package feed orchestrates the periodic scrape -> spam-filter ->
// SQLite-store pipeline that backs GET /tweets. The HTTP handler reads
// from the store so the phone never waits on a live scrape — at most
// it sees a feed that's ~interval minutes stale.
package feed

import (
	"context"
	"errors"
	"log/slog"
	"regexp"
	"strings"
	"time"

	"github.com/omarss/workspace/tweets/internal/events"
	"github.com/omarss/workspace/tweets/internal/scrape"
	"github.com/omarss/workspace/tweets/internal/server"
	"github.com/omarss/workspace/tweets/internal/spam"
	"github.com/omarss/workspace/tweets/internal/store"
)

// AuthRefresher kicks the CDP-driven script that re-arms cookies +
// search template by driving a server-resident Chrome through one
// search. Called from the loop on persistent ErrAuthFailed.
// nil → no auto-refresh.
type AuthRefresher interface {
	Refresh(ctx context.Context) error
}

// Loop runs the periodic refresh. Each tick scrapes every supported
// country in turn, drops spam-scored tweets above the threshold, scores
// the rest for event-relevance, and upserts to the store sorted by
// event-score desc. Errors are logged but never abort the loop — a bad
// scrape just means the next tick tries again. Persistent auth errors
// trigger the AuthRefresher (if configured) to refresh cookies + TID.
type Loop struct {
	scraper   scrape.Scraper
	store     *store.DB
	log       *slog.Logger
	refresher AuthRefresher

	interval      time.Duration
	maxPerCountry int
	spamThreshold float64
	retention     time.Duration
	authCooldown  time.Duration
	lastRefresh   time.Time
}

// Config tunables for the loop. Zero values fall back to sensible
// defaults — keeps the main.go wire-up readable.
//
// SpamThreshold default 0.5 is more aggressive than the original 0.7
// after the user's feedback that the unfiltered feed was full of
// "stupid spammers". Tweets with score > 0.5 (link spam, hashtag stuff,
// new-account all-caps) drop out before they hit the store.
type Config struct {
	Interval        time.Duration
	MaxPerCountry   int
	SpamThreshold   float64
	Retention       time.Duration
	AuthCooldown    time.Duration
	Refresher       AuthRefresher
}

func NewLoop(s scrape.Scraper, db *store.DB, log *slog.Logger, cfg Config) *Loop {
	if cfg.Interval <= 0 {
		cfg.Interval = 10 * time.Minute
	}
	if cfg.MaxPerCountry <= 0 {
		cfg.MaxPerCountry = 40
	}
	if cfg.SpamThreshold <= 0 {
		cfg.SpamThreshold = 0.5
	}
	if cfg.Retention <= 0 {
		cfg.Retention = 24 * time.Hour
	}
	if cfg.AuthCooldown <= 0 {
		cfg.AuthCooldown = 5 * time.Minute
	}
	if log == nil {
		log = slog.Default()
	}
	return &Loop{
		scraper:       s,
		store:         db,
		log:           log,
		refresher:     cfg.Refresher,
		interval:      cfg.Interval,
		maxPerCountry: cfg.MaxPerCountry,
		spamThreshold: cfg.SpamThreshold,
		retention:     cfg.Retention,
		authCooldown:  cfg.AuthCooldown,
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
		// On auth failure, kick the CDP refresher (with a cooldown
		// so a sustained outage doesn't open Chrome every 10 min).
		if errors.Is(err, scrape.ErrAuthFailed) {
			l.maybeRefreshAuth(ctx)
		}
		return
	}
	var (
		kept      = make([]server.Tweet, 0, len(tweets))
		spamDrops int
		eventHits int
	)
	// Per-tick author dedup. The scraper sometimes pulls in 3-7
	// near-identical posts from the same handle when X re-surfaces an
	// engagement-farming pattern (`#اهب_مكذبك_ياكذبان https://t.co/X`
	// posted three times in a row with different shortlink suffixes).
	// We flag everything except the first occurrence per (handle,
	// hashtag-bearing-text-sans-urls) as DuplicateRecent so the
	// existing 0.35 score penalty applies. Stripping URLs is the
	// trick — identical posts with different t.co suffixes match.
	seen := make(map[string]bool, len(tweets))
	for i := range tweets {
		t := &tweets[i]
		dupKey := t.Handle + "|" + normalizeForDedup(t.Text)
		dup := false
		if t.Handle != "" {
			if seen[dupKey] {
				dup = true
			} else {
				seen[dupKey] = true
			}
		}

		ss, _ := spam.Score(spam.Compute(t.Text, time.Time{}, 0, 0, dup))
		t.SpamScore = ss
		// >= so borderline 0.50 cases drop (was > before; the
		// blocklist comfortably puts real spam past 0.5, the strict
		// gate guards against score collisions).
		if ss >= l.spamThreshold {
			spamDrops++
			continue
		}
		ev := events.Compute(t.Text)
		t.EventScore = ev.Value
		t.EventCategories = ev.Categories
		if ev.Value > 0 {
			eventHits++
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
		"dropped_spam", spamDrops,
		"event_hits", eventHits,
	)
}

func (l *Loop) maybeRefreshAuth(ctx context.Context) {
	if l.refresher == nil {
		return
	}
	if !l.lastRefresh.IsZero() && time.Since(l.lastRefresh) < l.authCooldown {
		l.log.Info("auth refresh skipped (cooldown)",
			"cooldown", l.authCooldown,
			"last", l.lastRefresh.UTC())
		return
	}
	l.lastRefresh = time.Now()
	l.log.Warn("triggering auth refresh")
	if err := l.refresher.Refresh(ctx); err != nil {
		l.log.Error("auth refresh failed", "err", err)
		return
	}
	l.log.Info("auth refresh succeeded — next scrape will reload credentials")
	// Best-effort reload so the next tick picks up new files.
	if rl, ok := l.scraper.(reloadable); ok {
		if err := rl.Reload(); err != nil {
			l.log.Warn("scraper reload after auth refresh failed", "err", err)
		}
	}
}

// reloadable is satisfied by *scrape.HTTPScraper. Kept as an unexported
// interface here so the loop can stay decoupled from the concrete impl
// (tests substitute fakes that don't need to reload anything).
type reloadable interface {
	Reload() error
}

// normalizeForDedup lowercases + strips URLs + collapses whitespace so
// the same logical post with different t.co shortlink suffixes still
// hashes to the same key. We DON'T strip hashtags — the dedup signal
// hinges on identical hashtag content from the same handle.
var dedupUrlRe = regexp.MustCompile(`https?://\S+|t\.co/\S+`)
var dedupSpaceRe = regexp.MustCompile(`\s+`)

func normalizeForDedup(text string) string {
	low := strings.ToLower(text)
	low = dedupUrlRe.ReplaceAllString(low, "")
	low = dedupSpaceRe.ReplaceAllString(low, " ")
	return strings.TrimSpace(low)
}
