package server

import (
	"context"
	"errors"
	"log/slog"
	"sort"
	"time"
)

// StoreReader is the subset of the SQLite store the HTTP handler needs.
// Keeping it as a tiny interface lets us swap in a fake for tests
// without depending on the store package directly.
type StoreReader interface {
	// Latest returns up to `limit` tweets matching any of the given
	// countries with created_at < cursor (cursor zero = no upper
	// bound). Newest first. Cities is an optional list of
	// case-insensitive substrings matched against tweet.place; empty
	// means "no city filter". Query is an optional whitespace-tokenised
	// AND keyword filter applied to the tweet body; empty means "no
	// keyword filter".
	Latest(ctx context.Context, countries []Country, cities []string, query string, cursor time.Time, limit int) ([]Tweet, error)
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
	tweets, err := c.store.Latest(ctx, req.Countries, req.Cities, req.Query, req.Cursor, limit)
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
