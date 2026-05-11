// Package server wires the bot's tiny HTTP surface: /healthz for
// liveness/readiness probes and /webhooks/twilio/whatsapp for Twilio's
// inbound message webhook.
//
// The Telegram path uses long-poll, so it doesn't need an inbound HTTP
// route — it's driven by a goroutine in cmd/bot/main.go.
package server

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"

	"github.com/omarss/qudrat-bot/internal/handler"
	"github.com/omarss/qudrat-bot/internal/transport/whatsapp"
)

// Config controls the router. WA may be nil if Twilio isn't configured;
// the /webhooks/twilio route then returns 503.
type Config struct {
	Version string
	Handler *handler.Handler
	WA      *whatsapp.Client
	Logger  *slog.Logger
}

// New returns a chi router with the platform middlewares + the operational
// and webhook routes.
func New(cfg Config) chi.Router {
	if cfg.Logger == nil {
		cfg.Logger = slog.Default()
	}
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Recoverer)

	r.Get("/healthz", healthz)
	r.Get("/", indexBanner(cfg.Version))

	r.Post("/webhooks/twilio/whatsapp", twilioWhatsAppHandler(cfg))
	return r
}

func healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func indexBanner(version string) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"service": "qudrat-bot", "version": version})
	}
}

func twilioWhatsAppHandler(cfg Config) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if cfg.WA == nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "whatsapp not configured"})
			return
		}
		if err := r.ParseForm(); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid form"})
			return
		}
		// Validate the signature against the publicly visible URL — host
		// nginx terminates TLS upstream of us, so reconstruct the https
		// scheme using the X-Forwarded-Proto header.
		signedURL := publicURL(r)
		sig := r.Header.Get("X-Twilio-Signature")
		if !cfg.WA.ValidateSignature(signedURL, r.PostForm, sig) {
			cfg.Logger.Warn("twilio signature invalid", "url", signedURL)
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "bad signature"})
			return
		}
		msg, err := whatsapp.ParseWebhook(r)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		// Ack Twilio fast; do the actual work in a detached goroutine.
		go cfg.Handler.HandleWhatsApp(r.Context(), cfg.WA, msg)
		w.WriteHeader(http.StatusNoContent)
	}
}

func publicURL(r *http.Request) string {
	scheme := r.Header.Get("X-Forwarded-Proto")
	if scheme == "" {
		scheme = "https"
	}
	host := r.Host
	if h := r.Header.Get("X-Forwarded-Host"); h != "" {
		host = h
	}
	return scheme + "://" + host + r.URL.RequestURI()
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
