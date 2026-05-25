package server

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"time"
)

// FeedSource produces the current feed for a given country. The
// Android-facing handler is decoupled from how the tweets are actually
// fetched — Phase 1 ships an in-memory fixture source so the contract is
// proven before the scraper lands.
type FeedSource interface {
	Feed(ctx context.Context, country Country) ([]Tweet, error)
}

// ErrUnknownCountry is returned when a caller asks for a feed the
// configured source doesn't recognise. Mapped to HTTP 400 at the edge.
var ErrUnknownCountry = errors.New("unknown country")

// Server wires the FeedSource into an HTTP mux. It is intentionally
// minimal — no middleware framework, no router library; the entire app
// is two endpoints and the request rate is one bored user.
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

// Routes returns an http.Handler with /healthz and /tweets wired.
// Separating from Server's struct so tests can mount the routes without
// constructing a Server.
func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.health)
	mux.HandleFunc("GET /tweets", s.tweets)
	return mux
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, HealthResponse{Status: "ok"})
}

func (s *Server) tweets(w http.ResponseWriter, r *http.Request) {
	country := Country(r.URL.Query().Get("country"))
	if country == "" {
		country = CountryKSA // default — phone won't always send the param
	}
	tweets, err := s.source.Feed(r.Context(), country)
	if err != nil {
		if errors.Is(err, ErrUnknownCountry) {
			http.Error(w, "unknown country", http.StatusBadRequest)
			return
		}
		s.log.Error("feed lookup failed", "country", country, "err", err)
		http.Error(w, "feed unavailable", http.StatusBadGateway)
		return
	}
	writeJSON(w, http.StatusOK, FeedResponse{
		Country:     country,
		GeneratedAt: time.Now().UTC(),
		Tweets:      tweets,
	})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
