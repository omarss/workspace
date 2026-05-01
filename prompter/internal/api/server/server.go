// Package server wires the HTTP router for the prompter api service.
//
// The router is constructed independently of the listening loop so handlers
// can be exercised with httptest in unit tests without binding a port.
package server

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

// Config holds the runtime knobs the router needs. Fields will grow as the
// auth, store, and inference packages come online.
type Config struct {
	Version string
}

// New returns a chi router with the platform middlewares (request id, logger,
// recoverer) and the operational endpoints (/healthz, /readyz) wired up.
// Domain routes are added by callers via the returned router.
func New(cfg Config) chi.Router {
	r := chi.NewRouter()

	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)

	r.Get("/healthz", healthz)
	r.Get("/readyz", readyz)

	return r
}

// healthz reports liveness. It always returns 200; failures here mean the
// process is dead and the kubelet should restart it.
func healthz(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("content-type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("ok"))
}

// readyz reports readiness to serve traffic. Once the store and inference
// dependencies are wired, this will gate on their probes.
func readyz(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("content-type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("ready"))
}
