package server

import (
	"context"
	"errors"
	"log/slog"
)

// StoreReader is the subset of the SQLite store the HTTP handler needs.
// Keeping it as a tiny interface lets us swap in a fake for tests
// without depending on the store package directly.
type StoreReader interface {
	Latest(ctx context.Context, country Country, limit int) ([]Tweet, error)
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
		limit = 50
	}
	if log == nil {
		log = slog.Default()
	}
	return &CachedSource{store: store, fallback: fallback, limit: limit, log: log}
}

func (c *CachedSource) Feed(ctx context.Context, country Country) ([]Tweet, error) {
	tweets, err := c.store.Latest(ctx, country, c.limit)
	if err != nil {
		c.log.Warn("store read failed; falling back to fixture", "country", country, "err", err)
		return c.fallback.Feed(ctx, country)
	}
	if len(tweets) == 0 {
		// Distinguish "no rows yet" from "unknown country" — only fall
		// back to fixture when the fixture itself accepts the country.
		fallback, fbErr := c.fallback.Feed(ctx, country)
		if errors.Is(fbErr, ErrUnknownCountry) {
			return nil, ErrUnknownCountry
		}
		return fallback, nil
	}
	return tweets, nil
}
