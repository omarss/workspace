// Package server wires the HTTP router for the qudrat api service.
//
// The router is constructed independently of the listening loop so handlers
// can be exercised with httptest in unit tests without binding a port.
package server

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

// DBPinger is what the readyz handler needs from the store: a way to verify
// the database is reachable. pgxpool.Pool satisfies this naturally, but
// keeping it as an interface lets the unit tests pass a stub.
type DBPinger interface {
	Ping(ctx context.Context) error
}

// Config holds the runtime knobs the router needs.
type Config struct {
	Version string
	DB      DBPinger
}

// New returns a chi router with the platform middlewares (request id, logger,
// recoverer) and the operational endpoints (/healthz, /readyz, /) wired up.
// Domain routes are added by callers via the returned router.
func New(cfg Config) chi.Router {
	r := chi.NewRouter()

	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)

	r.Get("/", indexHandler(cfg.Version))
	r.Get("/healthz", healthz)
	r.Get("/readyz", readyz(cfg.DB))

	return r
}

// indexHandler returns a small JSON banner so curling the bare host
// confirms the service is reachable. Real product surface lives at /api in
// later phases.
func indexHandler(version string) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{
			"service": "qudrat",
			"version": version,
		})
	}
}

// healthz reports liveness. It always returns 200; failures here mean the
// process is dead and the kubelet should restart it.
func healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// readyz reports readiness to serve traffic. When a DBPinger is configured,
// readiness gates on a 1s Ping; absent one (e.g. in unit tests), the probe
// reports ready immediately.
func readyz(db DBPinger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if db == nil {
			writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "db": "skipped"})
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 1*time.Second)
		defer cancel()
		if err := db.Ping(ctx); err != nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{
				"status": "not_ready",
				"db":     "error",
			})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "db": "ok"})
	}
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("content-type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
