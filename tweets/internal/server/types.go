// Package server defines the wire types the tweets service emits and the
// HTTP surface the Android client consumes. Wire format is kept
// deliberately small — every byte travels over a phone radio.
package server

import "time"

// Country selects which feed the client wants. The service holds a small
// fixed set; anything outside it returns 400. Mapping to scraper queries
// happens in package scrape.
type Country string

const (
	CountryKSA   Country = "ksa"
	CountryEgypt Country = "eg"
)

// Tweet is the wire shape returned by GET /tweets. Fields are populated
// best-effort from whichever upstream produces them; everything except
// Text + ID is allowed to be empty when the source omits it.
//
// SpamScore is the heuristic score in [0, 1] computed by package spam.
// Clients receive only tweets below the service's drop threshold, so a
// non-zero value here just means "passed the filter but isn't squeaky
// clean" — useful for de-emphasising borderline content in the UI.
//
// EventScore + EventCategories drive the "events and registration"
// emphasis: the feed is sorted event-score descending on the first page
// so concerts, festivals, workshops, ticket releases etc. float above
// generic location-tagged chatter. EventCategories names the matched
// event vocabulary buckets (ticket / concert / festival / workshop / talk
// / sports / opening / venue / schedule) so the UI can render a small
// badge per row.
//
// AvatarURL is the author's profile picture from
// `result.core.avatar.image_url`. The Twitter `_normal` variant
// (~48x48); the Android client renders into a 32–40dp circle. Empty
// when the upstream omits it (deleted account, animated PFP we don't
// render, etc.) — UI falls back to an initial letter.
type Tweet struct {
	ID              string    `json:"id"`
	Author          string    `json:"author"`
	Handle          string    `json:"handle"`
	Text            string    `json:"text"`
	CreatedAt       time.Time `json:"created_at"`
	Lang            string    `json:"lang,omitempty"`
	Place           string    `json:"place,omitempty"`
	Country         Country   `json:"country"`
	ReplyCount      int       `json:"reply_count"`
	LikeCount       int       `json:"like_count"`
	RetweetCount    int       `json:"retweet_count"`
	SpamScore       float64   `json:"spam_score"`
	EventScore      float64   `json:"event_score"`
	EventCategories []string  `json:"event_categories,omitempty"`
	AvatarURL       string    `json:"avatar_url,omitempty"`
}

// FeedRequest collects the per-request filter / pagination parameters
// the HTTP handler parses from the query string. Centralised so the
// store / source layers can grow alongside the wire shape without
// rewiring the handler each time.
type FeedRequest struct {
	// Countries is the union of allowed country codes; empty defaults
	// to KSA only (back-compat with single-country callers).
	Countries []Country
	// Cities is a list of case-insensitive substrings matched against
	// the tweet's `place` field. Empty means "no city filter, all
	// places within the selected countries pass". OR semantics — a
	// tweet whose place contains any one substring matches.
	Cities []string
	// Cursor is an RFC3339 timestamp; only tweets with `created_at`
	// strictly less than this pass. Zero value means "first page" and
	// triggers event-first sort for the response.
	Cursor time.Time
	// Limit caps the response size. 0 → handler default (60).
	Limit int
}

// FeedResponse is the envelope for GET /tweets.
//
// NextCursor is the RFC3339 timestamp the client passes as `?cursor=`
// on the next request to fetch older tweets. Empty when the server has
// no more rows to return (the client stops infinite scrolling).
type FeedResponse struct {
	Countries   []Country `json:"countries"`
	Cities      []string  `json:"cities,omitempty"`
	GeneratedAt time.Time `json:"generated_at"`
	NextCursor  string    `json:"next_cursor,omitempty"`
	Tweets      []Tweet   `json:"tweets"`
}

// HealthResponse is the body of GET /healthz.
type HealthResponse struct {
	Status string `json:"status"`
}
