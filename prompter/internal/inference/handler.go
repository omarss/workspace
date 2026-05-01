package inference

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"
)

// Handler exposes inference-adjacent HTTP routes (model registry today;
// usage stats later).
type Handler struct {
	svc    *Service
	logger *slog.Logger
}

// NewHandler wires the dependencies. logger=nil falls back to slog.Default.
func NewHandler(s *Service, logger *slog.Logger) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{svc: s, logger: logger}
}

// Mount registers the routes on r. Caller decides the prefix (typically /api).
func (h *Handler) Mount(r chi.Router) {
	r.Get("/models", h.listModels)
}

func (h *Handler) listModels(w http.ResponseWriter, r *http.Request) {
	models, err := h.svc.ListModels(r.Context())
	if err != nil {
		h.logger.Error("list models", "err", err)
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"models": models})
}
