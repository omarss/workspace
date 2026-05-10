// Command worker runs the asynchronous job consumer for qudrat.
//
// Phase 1 placeholder. Phase 4 wires real jobs (calibration sweeps,
// reviewer-pipeline triggers, leaderboard rollups). The binary exists now
// so the build matrix and container layout match the api service from
// day one.
package main

import (
	"log/slog"
	"os"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	logger.Info("worker placeholder; job queue not wired yet")
}
