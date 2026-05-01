// Command worker runs the asynchronous job queue consumer for prompter.
//
// Wired in detail when the submission grading flow lands. For now this binary
// exists so the build matrix and container layout match the api service from
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
	logger.Info("worker placeholder; grading queue not wired yet")
}
