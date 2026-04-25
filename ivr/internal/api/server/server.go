// Package server builds the http.Handler exposed by the tenant API service.
//
// The handler is constructed via New(Config) so cmd/api can wire dependencies
// (logger, version, future stores) in main while tests exercise the handler
// in-process via httptest.
package server

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

// Config bundles construction-time dependencies.
type Config struct {
	Logger  *slog.Logger
	Version string
}

// New returns an http.Handler implementing the tenant API surface.
// Today: liveness + readiness only. Routes are added in subsequent phases.
func New(cfg Config) (http.Handler, error) {
	if cfg.Logger == nil {
		return nil, errors.New("server: nil logger")
	}
	if cfg.Version == "" {
		cfg.Version = "dev"
	}

	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(slogMiddleware(cfg.Logger))
	r.Use(middleware.Recoverer)

	r.Get("/healthz", healthHandler(cfg.Version, "ok"))
	r.Get("/readyz", healthHandler(cfg.Version, "ready"))

	return r, nil
}

func healthHandler(version, status string) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{
			"status":  status,
			"version": version,
		})
	}
}

// slogMiddleware emits a structured log line per request and copies the
// request id into the response header for client-side correlation.
func slogMiddleware(logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			rid := middleware.GetReqID(r.Context())
			if rid != "" {
				w.Header().Set("X-Request-Id", rid)
			}
			ww := middleware.NewWrapResponseWriter(w, r.ProtoMajor)
			next.ServeHTTP(ww, r)
			logger.LogAttrs(r.Context(), slog.LevelInfo, "http",
				slog.String("method", r.Method),
				slog.String("path", r.URL.Path),
				slog.Int("status", ww.Status()),
				slog.Int("bytes", ww.BytesWritten()),
				slog.String("rid", rid),
			)
		})
	}
}
