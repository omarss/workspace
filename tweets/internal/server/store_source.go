package server

import (
	"context"
	"errors"
	"log/slog"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/omarss/workspace/tweets/internal/query"
)

// StoreReader is the subset of the SQLite store the HTTP handler needs.
// Keeping it as a tiny interface lets us swap in a fake for tests
// without depending on the store package directly.
type StoreReader interface {
	// Latest returns up to `limit` tweets matching any of the given
	// countries with created_at < cursor (cursor zero = no upper
	// bound). Newest first. Cities is an optional list of
	// case-insensitive substrings matched against tweet.place; empty
	// means "no city filter". QueryExpr is an optional parsed boolean
	// expression matched against the tweet body; nil means "no
	// keyword filter".
	Latest(ctx context.Context, countries []Country, cities []string, queryExpr query.Expr, cursor time.Time, limit int) ([]Tweet, error)
}

// CachedSource reads from a StoreReader and falls back to a secondary
// FeedSource (typically FixtureSource) when the store is empty or
// errors. This is what keeps the UI populated during a fresh deploy
// or a temporary scrape outage.
type CachedSource struct {
	store    StoreReader
	fallback FeedSource
	limit    int
	log      *slog.Logger
}

func NewCachedSource(store StoreReader, fallback FeedSource, limit int, log *slog.Logger) *CachedSource {
	if limit <= 0 {
		limit = 60
	}
	if log == nil {
		log = slog.Default()
	}
	return &CachedSource{store: store, fallback: fallback, limit: limit, log: log}
}

// Feed satisfies FeedSource. Pages of tweets behave as follows:
//
//   * First page (cursor == zero) is sorted event-first, then by
//     created_at desc, so events float to the top.
//   * Subsequent pages (cursor != zero) are chronological — they
//     extend the timeline; reordering by event score on every
//     subsequent page would cause tweets to "jump up" as the user
//     scrolls past them, which is disorienting.
//   * NextCursor on the response is the oldest created_at the client
//     saw in this batch. Empty when fewer than `limit` rows came
//     back (no more pages).
func (c *CachedSource) Feed(ctx context.Context, req FeedRequest) (FeedResult, error) {
	limit := req.Limit
	if limit <= 0 {
		limit = c.limit
	}
	// In magic mode the curated keyword expression matches < 1% of
	// rows in the live store (~7 of 1900 at 2026-05-26). The store's
	// default over-fetch (limit*3 capped at 600 internally) covers
	// only the most recent ~6 hours of scrapes, so the older half of
	// the retention window's matches were silently dropped — the
	// user-visible "magic shows only 2 tweets" bug.
	//
	// Ask the store for the full retention window's worth so every
	// match surfaces, then the spam-gate + dedup + page-trim below
	// cut back to the caller's requested limit.
	storeLimit := limit
	if req.Magic {
		storeLimit = 5000
	}
	tweets, err := c.store.Latest(ctx, req.Countries, req.Cities, req.QueryExpr, req.Cursor, storeLimit)
	if err != nil {
		c.log.Warn("store read failed; falling back to fixture", "err", err)
		fb, fbErr := c.fallback.Feed(ctx, req)
		if fbErr != nil {
			return FeedResult{}, fbErr
		}
		return fb, nil
	}
	if len(tweets) == 0 {
		// Empty store → fall back to fixture so the UI is never blank.
		// Errors from the fallback (e.g. unknown country) propagate.
		fb, fbErr := c.fallback.Feed(ctx, req)
		if errors.Is(fbErr, ErrUnknownCountry) {
			return FeedResult{}, ErrUnknownCountry
		}
		if fbErr != nil {
			return FeedResult{}, fbErr
		}
		return fb, nil
	}

	// Magic mode: extra quality gate. The default store gate dropped
	// rows with spam_score >= 0.45, but the curated keyword set is
	// itself ad-adjacent (commercial Arabic vocabulary overlaps with
	// event vocabulary), so we tighten to 0.25 specifically when the
	// user opted into magic.
	//
	// Also: cross-tick dedup by (handle, normalized body). The
	// per-tick dedup in feed/loop only sees one scrape at a time, so
	// a bot reposting the same body with a fresh t.co URL every hour
	// leaves three rows in the store that all pass the magic filter.
	// We drop the duplicates here on the read path, keeping the
	// newest.
	if req.Magic {
		kept := tweets[:0]
		seen := make(map[string]bool, len(tweets))
		for _, tw := range tweets {
			if tw.SpamScore > 0.25 {
				continue
			}
			dupKey := tw.Handle + "|" + magicDedupKey(tw.Text)
			if tw.Handle != "" && seen[dupKey] {
				continue
			}
			if tw.Handle != "" {
				seen[dupKey] = true
			}
			kept = append(kept, tw)
		}
		tweets = kept
		// Trim back to the caller's requested limit after the gate.
		if len(tweets) > limit {
			tweets = tweets[:limit]
		}
	}

	if req.Cursor.IsZero() {
		// First page — re-sort event-first in memory.
		sortFeedEventFirst(tweets)
	}
	result := FeedResult{Tweets: tweets}
	// Cursor points at the oldest tweet we returned. Set only when
	// we filled the page — partial pages mean no more rows.
	if len(tweets) >= limit {
		oldest := tweets[0].CreatedAt
		for _, tw := range tweets {
			if tw.CreatedAt.Before(oldest) {
				oldest = tw.CreatedAt
			}
		}
		result.NextCursor = oldest
	}
	return result, nil
}

// magicDedupKey normalises a tweet body for cross-tick dedup: strip
// URLs, collapse whitespace, lowercase. Same shape the per-tick dedup
// in feed/loop uses — kept separate here so the server package
// doesn't import the feed package.
var magicDedupUrlRe = regexp.MustCompile(`https?://\S+|t\.co/\S+`)
var magicDedupSpaceRe = regexp.MustCompile(`\s+`)

func magicDedupKey(text string) string {
	low := strings.ToLower(text)
	low = magicDedupUrlRe.ReplaceAllString(low, "")
	low = magicDedupSpaceRe.ReplaceAllString(low, " ")
	return strings.TrimSpace(low)
}

// sortFeedEventFirst orders the slice in place so high-event-score
// tweets land at the top, with ties broken by created_at desc.
// Stable so same-score same-time tweets keep their store order.
func sortFeedEventFirst(in []Tweet) {
	sort.SliceStable(in, func(i, j int) bool {
		if in[i].EventScore != in[j].EventScore {
			return in[i].EventScore > in[j].EventScore
		}
		return in[i].CreatedAt.After(in[j].CreatedAt)
	})
}
