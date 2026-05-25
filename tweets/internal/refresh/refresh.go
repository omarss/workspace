// Package refresh shells out to scripts/refresh-template.py to re-arm
// the search template + cookie jar from the server-resident Chrome.
// It's the bridge between the Go scraper (HTTP) and the Python CDP
// client.
package refresh

import (
	"bytes"
	"context"
	"fmt"
	"log/slog"
	"os/exec"
	"time"
)

// Runner invokes the refresh script. Implements feed.AuthRefresher.
type Runner struct {
	PythonBin   string        // venv python, default /srv/tweets/refresh-venv/bin/python
	ScriptPath  string        // path to refresh-template.py
	DevToolsURL string        // default http://127.0.0.1:9222
	CookiesOut  string        // default /srv/tweets/cookies.json
	TemplateOut string        // default /srv/tweets/search-template.json
	Timeout     time.Duration // wall clock; defaults to 45s
	Log         *slog.Logger
}

func (r *Runner) Refresh(ctx context.Context) error {
	if r.PythonBin == "" {
		r.PythonBin = "/srv/tweets/refresh-venv/bin/python"
	}
	if r.ScriptPath == "" {
		return fmt.Errorf("refresh script path not set")
	}
	if r.DevToolsURL == "" {
		r.DevToolsURL = "http://127.0.0.1:9222"
	}
	if r.CookiesOut == "" {
		r.CookiesOut = "/srv/tweets/cookies.json"
	}
	if r.TemplateOut == "" {
		r.TemplateOut = "/srv/tweets/search-template.json"
	}
	if r.Timeout <= 0 {
		r.Timeout = 45 * time.Second
	}
	if r.Log == nil {
		r.Log = slog.Default()
	}

	subctx, cancel := context.WithTimeout(ctx, r.Timeout)
	defer cancel()

	cmd := exec.CommandContext(subctx, r.PythonBin,
		r.ScriptPath,
		"--devtools", r.DevToolsURL,
		"--cookies-out", r.CookiesOut,
		"--template-out", r.TemplateOut,
	)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	start := time.Now()
	err := cmd.Run()
	took := time.Since(start)

	// Stderr carries the human-readable progress log from the script,
	// stdout is empty on success — surface stderr regardless.
	stderrTrim := bytes.TrimSpace(stderr.Bytes())
	if err != nil {
		r.Log.Error("refresh-template failed",
			"err", err,
			"took", took,
			"stderr", string(stderrTrim))
		return fmt.Errorf("refresh: %w: %s", err, string(stderrTrim))
	}
	r.Log.Info("refresh-template succeeded", "took", took, "out", string(stderrTrim))
	return nil
}
