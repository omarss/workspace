// Binary tweetsd is the tweets feed service.
//
// Pipeline:
//
//	background loop  →  twitter scraper  →  spam filter  →  SQLite store
//	                                                            ↓
//	                                                       HTTP /tweets
//
// All scrape errors are logged and survived — the HTTP path keeps
// serving whatever's in the store, falling back to hand-crafted
// fixture data when the store is empty (fresh deploys, missing
// cookies). The phone is decoupled from twitter.com's availability.
package main

import (
	"context"
	"errors"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/omarss/workspace/tweets/internal/feed"
	"github.com/omarss/workspace/tweets/internal/scrape"
	"github.com/omarss/workspace/tweets/internal/server"
	"github.com/omarss/workspace/tweets/internal/store"
)

func main() {
	var (
		addr         = flag.String("addr", env("TWEETS_ADDR", ":8080"), "listen address")
		cookiesPath  = flag.String("cookies", env("TWEETS_COOKIES_PATH", "/srv/tweets/cookies.json"), "X session cookie file (JSON: auth_token + ct0)")
		dbPath       = flag.String("db", env("TWEETS_DB_PATH", "/srv/tweets/tweets.sqlite"), "SQLite cache file")
		intervalFlag = flag.Duration("interval", durEnv("TWEETS_REFRESH_INTERVAL", 10*time.Minute), "background refresh interval")
		readonly     = flag.Bool("readonly", false, "skip the scrape loop, serve store + fixtures only (useful for local dev without cookies)")
	)
	flag.Parse()

	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(log)

	if err := os.MkdirAll(filepath.Dir(*dbPath), 0o755); err != nil {
		log.Warn("could not ensure db parent dir", "path", *dbPath, "err", err)
	}
	db, err := store.Open(*dbPath)
	if err != nil {
		log.Error("store open failed", "err", err)
		os.Exit(1)
	}
	defer db.Close()

	fixture := server.NewFixtureSource()
	source := server.NewCachedSource(db, fixture, 50, log)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if !*readonly {
		startScrapeLoop(ctx, *cookiesPath, *intervalFlag, db, log)
	} else {
		log.Info("readonly mode — scrape loop disabled")
	}

	srv := &http.Server{
		Addr:              *addr,
		Handler:           server.New(source, log).Routes(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      15 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	go func() {
		log.Info("tweetsd listening", "addr", *addr, "readonly", *readonly)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("listen failed", "err", err)
			stop()
		}
	}()

	<-ctx.Done()
	log.Info("shutting down")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Error("shutdown failed", "err", err)
		os.Exit(1)
	}
}

// startScrapeLoop tries to build a logged-in scraper from the cookie
// file and launches the background loop. Failure to load cookies or
// log in is non-fatal — the service continues in "fixture-only" mode
// and logs prominently so the operator notices.
func startScrapeLoop(
	ctx context.Context,
	cookiesPath string,
	interval time.Duration,
	db *store.DB,
	log *slog.Logger,
) {
	creds, err := scrape.LoadCredentials(cookiesPath)
	if err != nil {
		log.Warn("cookies not loaded — serving fixtures only",
			"path", cookiesPath, "err", err)
		return
	}
	twitter, err := scrape.NewTwitterScraper(creds)
	if err != nil {
		log.Warn("twitter session not authenticated — serving fixtures only",
			"err", err,
			"hint", "refresh "+cookiesPath+" with new auth_token + ct0 cookies")
		return
	}
	loop := feed.NewLoop(twitter, db, log, feed.Config{Interval: interval})
	go loop.Run(ctx)
	log.Info("scrape loop started", "interval", interval)
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func durEnv(key string, fallback time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return fallback
}
