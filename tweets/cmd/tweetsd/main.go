// Binary tweetsd is the tweets feed service. Phase 1 emits hand-crafted
// fixture data through an HTTP JSON surface so the Android client can be
// built against a stable contract; Phase 2 swaps in a real scraper (see
// /tmp/omono-twitter/tweets/internal/scrape, planned) and the live spam
// filter without changing any wire types.
package main

import (
	"context"
	"errors"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/omarss/workspace/tweets/internal/server"
)

func main() {
	addr := flag.String("addr", ":8080", "listen address")
	flag.Parse()

	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(log)

	srv := &http.Server{
		Addr:              *addr,
		Handler:           server.New(server.NewFixtureSource(), log).Routes(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      15 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	go func() {
		log.Info("tweetsd listening", "addr", *addr)
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
