// Command worker runs the asynchronous jobs for qudrat.
//
// Phase 8 brings the calibration sweep online: the worker connects to
// Postgres, recomputes items.difficulty_calibrated for every item with
// enough attempts, and flags outliers for review. Run as a one-shot job
// from cron (or a Kubernetes CronJob); for long-running daemon mode add
// a ticker once we have more periodic jobs.
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/omarss/qudrat/internal/calibration"
	"github.com/omarss/qudrat/internal/config"
	"github.com/omarss/qudrat/internal/events"
	"github.com/omarss/qudrat/internal/store"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	if err := run(logger); err != nil {
		logger.Error("worker fatal", "err", err)
		os.Exit(1)
	}
}

func run(logger *slog.Logger) error {
	job := flag.String("job", "calibrate", "which job to run: calibrate")
	minAttempts := flag.Int("min-attempts", 30, "minimum attempts before an item is calibrated")
	flag.Parse()

	cfg, err := config.Load()
	if err != nil {
		return err
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()

	pool, err := pgxpool.New(ctx, cfg.DatabaseDSN)
	if err != nil {
		return fmt.Errorf("pgxpool: %w", err)
	}
	defer pool.Close()
	if err := pool.Ping(ctx); err != nil {
		return fmt.Errorf("pg ping: %w", err)
	}
	q := store.New(pool)
	ev := events.NewService(q, logger)

	switch *job {
	case "calibrate":
		ev.Record(ctx, events.TypeCalibrationRunStart, nil, nil, nil)
		res, err := calibration.NewService(q, ev, logger).Run(ctx, *minAttempts)
		if err != nil {
			return fmt.Errorf("calibrate: %w", err)
		}
		ev.Record(ctx, events.TypeCalibrationRunComplete, nil, nil, map[string]any{
			"inspected": res.Inspected,
			"updated":   res.Updated,
			"flagged":   res.Flagged,
		})
		logger.Info("calibration done",
			"inspected", res.Inspected,
			"updated", res.Updated,
			"flagged", res.Flagged,
		)
		return nil
	default:
		return fmt.Errorf("unknown job %q", *job)
	}
}
