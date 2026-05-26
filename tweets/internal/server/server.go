package server

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// FeedSource produces the current feed for a request. The Android-facing
// handler is decoupled from how the tweets are actually fetched —
// scraper, fixtures, and the SQLite cache all implement the same
// interface so the handler stays trivial.
type FeedSource interface {
	Feed(ctx context.Context, req FeedRequest) (FeedResult, error)
}

// FeedResult is what a FeedSource returns. NextCursor (when non-zero)
// is the timestamp the handler echoes back so the client can paginate.
type FeedResult struct {
	Tweets     []Tweet
	NextCursor time.Time
}

// ErrUnknownCountry is returned when a caller asks for a feed the
// configured source doesn't recognise. Mapped to HTTP 400 at the edge.
var ErrUnknownCountry = errors.New("unknown country")

// Server wires the FeedSource into an HTTP mux.
type Server struct {
	source FeedSource
	log    *slog.Logger
}

func New(source FeedSource, log *slog.Logger) *Server {
	if log == nil {
		log = slog.Default()
	}
	return &Server{source: source, log: log}
}

func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.health)
	mux.HandleFunc("GET /tweets", s.tweets)
	return mux
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, HealthResponse{Status: "ok"})
}

// tweets handles GET /tweets with the following query parameters:
//
//   country   comma-separated country codes (default "ksa"). Each must
//             be a known Country; unknown → 400.
//   city      comma-separated case-insensitive substrings to match
//             against tweet.place. Empty → no city filter.
//   q         free-text keyword search, AND-ed whitespace tokens,
//             case-insensitive substring match against tweet body.
//             Empty → no keyword filter. Capped to 200 chars and
//             stripped of % and _ so the store's LIKE query stays safe.
//   cursor    RFC3339 timestamp. Tweets older than this returned.
//             Empty → first page (event-first sort).
//   limit     int, default 60, capped at 200.
//
// Back-compat note: the old single-country `?country=ksa` form still
// works because the comma-split returns a single-element slice.
func (s *Server) tweets(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	req, err := parseFeedRequest(q)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	result, err := s.source.Feed(r.Context(), req)
	if err != nil {
		if errors.Is(err, ErrUnknownCountry) {
			http.Error(w, "unknown country", http.StatusBadRequest)
			return
		}
		s.log.Error("feed lookup failed", "req", req, "err", err)
		http.Error(w, "feed unavailable", http.StatusBadGateway)
		return
	}
	resp := FeedResponse{
		Countries:   req.Countries,
		Cities:      req.Cities,
		Query:       req.Query,
		GeneratedAt: time.Now().UTC(),
		Tweets:      result.Tweets,
	}
	if !result.NextCursor.IsZero() {
		resp.NextCursor = result.NextCursor.UTC().Format(time.RFC3339Nano)
	}
	writeJSON(w, http.StatusOK, resp)
}

// parseFeedRequest reads + validates the query string into a FeedRequest.
// Trims whitespace around each comma-separated value so curl users with
// pretty URLs aren't punished.
func parseFeedRequest(q map[string][]string) (FeedRequest, error) {
	get := func(key string) string {
		if v, ok := q[key]; ok && len(v) > 0 {
			return v[0]
		}
		return ""
	}
	req := FeedRequest{}

	countriesRaw := get("country")
	if countriesRaw == "" {
		countriesRaw = string(CountryKSA)
	}
	for _, c := range strings.Split(countriesRaw, ",") {
		c = strings.TrimSpace(c)
		if c == "" {
			continue
		}
		cc := Country(strings.ToLower(c))
		if cc != CountryKSA && cc != CountryEgypt {
			return req, errors.New("unknown country: " + c)
		}
		req.Countries = append(req.Countries, cc)
	}
	if len(req.Countries) == 0 {
		req.Countries = []Country{CountryKSA}
	}

	if v := get("city"); v != "" {
		for _, c := range strings.Split(v, ",") {
			c = strings.TrimSpace(c)
			if c != "" {
				req.Cities = append(req.Cities, c)
			}
		}
	}

	if v := get("q"); v != "" {
		// Strip the LIKE wildcards so a caller can't smuggle them into
		// the store layer's substring match. Also cap length to keep
		// the SQL query bounded.
		v = strings.ReplaceAll(v, "%", " ")
		v = strings.ReplaceAll(v, "_", " ")
		if len(v) > 200 {
			v = v[:200]
		}
		req.Query = strings.TrimSpace(v)
	}

	if v := get("cursor"); v != "" {
		t, err := time.Parse(time.RFC3339Nano, v)
		if err != nil {
			t, err = time.Parse(time.RFC3339, v)
		}
		if err != nil {
			return req, errors.New("invalid cursor (want RFC3339): " + v)
		}
		req.Cursor = t.UTC()
	}

	if v := get("limit"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 {
			return req, errors.New("invalid limit (want positive int): " + v)
		}
		if n > 200 {
			n = 200
		}
		req.Limit = n
	}
	return req, nil
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
