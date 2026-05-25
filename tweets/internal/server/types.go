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
// emphasis: the feed is sorted event-score descending so concerts,
// festivals, workshops, ticket releases etc. float above generic
// location-tagged chatter. EventCategories names the matched event
// vocabulary buckets (ticket / concert / festival / workshop / talk /
// sports / opening / venue / schedule) so the UI can render a small
// badge per row.
type Tweet struct {
	ID         string    `json:"id"`
	Author     string    `json:"author"`           // display name
	Handle     string    `json:"handle"`           // @-stripped username
	Text       string    `json:"text"`             // body, plain text
	CreatedAt  time.Time `json:"created_at"`       // UTC
	Lang       string    `json:"lang,omitempty"`   // ISO-639-1 if known
	Place      string    `json:"place,omitempty"`  // human-readable place tag
	Country    Country   `json:"country"`          // which feed this came from
	ReplyCount int       `json:"reply_count"`
	LikeCount  int       `json:"like_count"`
	RetweetCount int     `json:"retweet_count"`
	SpamScore  float64   `json:"spam_score"`
	EventScore float64   `json:"event_score"`
	EventCategories []string `json:"event_categories,omitempty"`
}

// FeedResponse is the envelope for GET /tweets. Keeping the list under a
// named field leaves room to add cursor/pagination metadata later without
// a wire-format break.
type FeedResponse struct {
	Country     Country   `json:"country"`
	GeneratedAt time.Time `json:"generated_at"`
	Tweets      []Tweet   `json:"tweets"`
}

// HealthResponse is the body of GET /healthz.
type HealthResponse struct {
	Status string `json:"status"`
}
