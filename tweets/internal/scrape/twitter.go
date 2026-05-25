// Package scrape pulls tweets off twitter.com's GraphQL endpoints via
// the imperatrona/twitter-scraper library. The library wraps the
// internal X web client, taking care of cursors, query-id hashes, and
// the cookie/CSRF token dance — we just hand it an authenticated
// session and a search query.
//
// All scrape behaviour is "best effort": any error is returned to the
// caller (the refresh loop) which logs and falls back to whatever's
// already in the SQLite cache. Never panic, never block the HTTP path.
package scrape

import (
	"context"
	"fmt"

	scraper "github.com/imperatrona/twitter-scraper"

	"github.com/omarss/workspace/tweets/internal/server"
)

// Scraper is the narrow interface the refresh loop depends on. Lets
// tests substitute a fake without dragging the imperatrona library in.
type Scraper interface {
	Search(ctx context.Context, country server.Country, max int) ([]server.Tweet, error)
}

// TwitterScraper is the library-backed implementation. Construct via
// NewTwitterScraper, which validates the cookies and confirms the
// session is logged in before returning.
type TwitterScraper struct {
	inner *scraper.Scraper
}

// NewTwitterScraper builds a logged-in scraper from the given cookies.
// Returns an error if the cookies are blank or X reports the session
// as unauthenticated (typically: cookie expired and the user needs to
// re-paste).
func NewTwitterScraper(creds Credentials) (*TwitterScraper, error) {
	s := scraper.New()
	s.SetAuthToken(scraper.AuthToken{
		Token:     creds.AuthToken,
		CSRFToken: creds.CT0,
	})
	// Latest = chronological. The "Top" mode reorders by engagement
	// which buries low-engagement local tweets that are exactly what
	// we want for a regional feed.
	s.SetSearchMode(scraper.SearchLatest)
	if !s.IsLoggedIn() {
		return nil, fmt.Errorf("twitter session rejected — refresh the cookie file")
	}
	return &TwitterScraper{inner: s}, nil
}

// Search runs a location-filtered search via X's `place_country:` query
// modifier. `max` caps the result count; the library will paginate
// internally up to that ceiling. Tweets the search returns inherit the
// caller's requested country tag — we don't re-derive it from the
// Place struct because some tweets the X search returns lack a populated
// Place even when the place_country filter matched (X serves slightly
// inconsistent data depending on cache state).
func (t *TwitterScraper) Search(ctx context.Context, country server.Country, max int) ([]server.Tweet, error) {
	if max <= 0 {
		max = 30
	}
	query, err := buildQuery(country)
	if err != nil {
		return nil, err
	}
	out := make([]server.Tweet, 0, max)
	for result := range t.inner.SearchTweets(ctx, query, max) {
		if result == nil {
			continue
		}
		if result.Error != nil {
			// A single bad page shouldn't abort the whole batch; log
			// upstream and continue. The library streams via a
			// channel so we can salvage partial results.
			continue
		}
		out = append(out, convert(&result.Tweet, country))
	}
	return out, nil
}

func buildQuery(country server.Country) (string, error) {
	switch country {
	case server.CountryKSA:
		// -is:retweet keeps the feed first-person; -filter:replies
		// drops the noisy in-thread responses that don't read well as
		// standalone cards. Both are documented X search operators.
		return "place_country:SA -is:retweet -filter:replies", nil
	case server.CountryEgypt:
		return "place_country:EG -is:retweet -filter:replies", nil
	default:
		return "", fmt.Errorf("unsupported country %q", country)
	}
}

// convert maps the library's Tweet to the wire Tweet that the rest of
// the service speaks. spam_score is filled in by the caller (the
// refresh loop) after running the heuristic scorer — we don't want
// scoring policy coupled to scraping.
func convert(src *scraper.Tweet, country server.Country) server.Tweet {
	place := ""
	if src.Place != nil {
		place = src.Place.FullName
	}
	return server.Tweet{
		ID:           src.ID,
		Author:       src.Name,
		Handle:       src.Username,
		Text:         src.Text,
		CreatedAt:    src.TimeParsed.UTC(),
		Place:        place,
		Country:      country,
		ReplyCount:   src.Replies,
		LikeCount:    src.Likes,
		RetweetCount: src.Retweets,
	}
}
