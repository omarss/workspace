// Command api serves the qudrat HTTP API.
//
// The binary stays small on purpose: it loads config, opens the Postgres
// pool, builds the chi router, and runs an http.Server with production-sane
// timeouts. Domain wiring (auth, items, attempts) lands in later phases.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/omarss/qudrat/internal/api/server"
	"github.com/omarss/qudrat/internal/config"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	if err := run(logger); err != nil {
		logger.Error("api fatal", "err", err)
		os.Exit(1)
	}
}

// run holds main's logic so deferred cleanups still fire on any error path.
// main() must remain os.Exit-only.
func run(logger *slog.Logger) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	bootCtx, bootCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer bootCancel()

	pool, err := pgxpool.New(bootCtx, cfg.DatabaseDSN)
	if err != nil {
		return fmt.Errorf("pgxpool: %w", err)
	}
	defer pool.Close()
	if err := pool.Ping(bootCtx); err != nil {
		return fmt.Errorf("pg ping: %w", err)
	}

	r := server.New(server.Config{
		Version: cfg.Version,
		DB:      pool,
	})

	srv := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           r,
		ReadHeaderTimeout: cfg.ReadHeaderTimeout,
		// IdleTimeout tames keep-alive connections hanging on through pod
		// restarts; matches the nginx upstream keepalive window.
		IdleTimeout: 60 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	listenErr := make(chan error, 1)
	go func() {
		logger.Info("api listening", "addr", cfg.HTTPAddr, "version", cfg.Version)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			listenErr <- err
			return
		}
		listenErr <- nil
	}()

	select {
	case err := <-listenErr:
		return err
	case <-ctx.Done():
		logger.Info("shutting down")
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return srv.Shutdown(shutdownCtx)
}
