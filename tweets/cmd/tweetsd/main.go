// Binary tweetsd is the tweets feed service.
//
// Pipeline:
//
//	background loop  ─► HTTPScraper ─► spam + event filter ─► SQLite store
//	      │                                                       │
//	      ▼ on auth failure                                       ▼
//	  Refresher → CDP → headless Chrome                       HTTP /tweets
//
// The phone calls /tweets which reads from the SQLite store with a
// fixture fallback — no twitter.com request ever runs in the HTTP path.
// The headless Chrome (tweets-browser.service) holds the authenticated
// session; the refresher re-arms cookies + the search-template signature
// hourly and on demand when the scraper reports auth failure.
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
	"strconv"
	"syscall"
	"time"

	"github.com/omarss/workspace/tweets/internal/feed"
	"github.com/omarss/workspace/tweets/internal/refresh"
	"github.com/omarss/workspace/tweets/internal/scrape"
	"github.com/omarss/workspace/tweets/internal/server"
	"github.com/omarss/workspace/tweets/internal/store"
)

func main() {
	var (
		addr          = flag.String("addr", env("TWEETS_ADDR", ":8080"), "listen address")
		cookiesPath   = flag.String("cookies", env("TWEETS_COOKIES_PATH", "/srv/tweets/cookies.json"), "X session cookie file (full jar JSON)")
		templatePath  = flag.String("template", env("TWEETS_TEMPLATE_PATH", "/srv/tweets/search-template.json"), "SearchTimeline URL + headers captured from CDP")
		dbPath        = flag.String("db", env("TWEETS_DB_PATH", "/srv/tweets/tweets.sqlite"), "SQLite cache file")
		intervalFlag  = flag.Duration("interval", durEnv("TWEETS_REFRESH_INTERVAL", 10*time.Minute), "background scrape interval")
		refreshEvery  = flag.Duration("auth-refresh-every", durEnv("TWEETS_AUTH_REFRESH_EVERY", 1*time.Hour), "preemptive CDP refresh cadence")
		refreshScript = flag.String("refresh-script", env("TWEETS_REFRESH_SCRIPT", "/srv/tweets/refresh-template.py"), "path to refresh-template.py")
		refreshVenv   = flag.String("refresh-venv-python", env("TWEETS_REFRESH_VENV_PYTHON", "/srv/tweets/refresh-venv/bin/python"), "python from the refresh-venv")
		spamThreshold = flag.Float64("spam-threshold", floatEnv("TWEETS_SPAM_THRESHOLD", 0.5), "drop tweets scoring above this [0,1]")
		readonly      = flag.Bool("readonly", false, "skip the scrape loop, serve store + fixtures only")
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
	source := server.NewCachedSource(db, fixture, 60, log)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if !*readonly {
		startScrapeLoop(ctx, *cookiesPath, *templatePath, *intervalFlag,
			*refreshEvery, *refreshScript, *refreshVenv, *spamThreshold,
			db, log)
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

// startScrapeLoop builds the HTTP scraper from the on-disk template +
// cookies and launches the periodic refresh loop. If either file is
// missing or unparseable on startup, the service falls back to
// fixture-only mode and logs prominently — the operator runs the
// refresh-template script once (via `make tweets-refresh`) to seed
// the credentials.
func startScrapeLoop(
	ctx context.Context,
	cookiesPath, templatePath string,
	interval, refreshEvery time.Duration,
	refreshScript, refreshVenv string,
	spamThreshold float64,
	db *store.DB,
	log *slog.Logger,
) {
	s, err := scrape.NewHTTPScraper(cookiesPath, templatePath)
	if err != nil {
		log.Warn("scraper init failed — serving fixtures only",
			"err", err,
			"hint", "run `make tweets-refresh` to capture cookies + template")
		return
	}

	refresher := &refresh.Runner{
		PythonBin:   refreshVenv,
		ScriptPath:  refreshScript,
		CookiesOut:  cookiesPath,
		TemplateOut: templatePath,
		Log:         log,
	}

	loop := feed.NewLoop(s, db, log, feed.Config{
		Interval:      interval,
		SpamThreshold: spamThreshold,
		Refresher:     refresher,
	})

	go loop.Run(ctx)

	// Pre-emptive periodic refresh — independent of the scrape interval
	// so we don't accumulate session drift even when scrapes are
	// succeeding.
	go runRefresherTicker(ctx, refresher, refreshEvery, log)

	log.Info("scrape loop started",
		"interval", interval,
		"refresh_every", refreshEvery,
		"spam_threshold", spamThreshold)
}

func runRefresherTicker(ctx context.Context, r *refresh.Runner, every time.Duration, log *slog.Logger) {
	if every <= 0 {
		return
	}
	t := time.NewTicker(every)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			if err := r.Refresh(ctx); err != nil {
				log.Warn("preemptive auth refresh failed", "err", err)
			}
		}
	}
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

func floatEnv(key string, fallback float64) float64 {
	if v := os.Getenv(key); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return fallback
}
