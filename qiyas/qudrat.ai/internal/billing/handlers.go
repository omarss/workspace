package billing

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"

	"github.com/omarss/qudrat/internal/auth"
)

// Handler exposes the user-facing billing surface.
type Handler struct {
	svc    *Service
	logger *slog.Logger
}

// NewHandler wires deps. logger=nil falls back to slog.Default.
func NewHandler(svc *Service, logger *slog.Logger) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{svc: svc, logger: logger}
}

// Mount registers the routes. Must be mounted under RequireSession.
func (h *Handler) Mount(r chi.Router) {
	r.Get("/me/subscription", h.subscription)
	r.Post("/me/subscription/cancel", h.cancel)
}

func (h *Handler) subscription(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	ent, err := h.svc.GetEntitlements(r.Context(), user.ID)
	if err != nil {
		h.logger.Error("entitlements", "err", err, "user", user.ID)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	writeJSON(w, http.StatusOK, ent)
}

func (h *Handler) cancel(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	if err := h.svc.Cancel(r.Context(), user.ID); err != nil {
		h.logger.Error("cancel", "err", err, "user", user.ID)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
