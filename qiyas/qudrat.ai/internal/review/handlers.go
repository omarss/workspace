package review

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

// Handler exposes the reviewer-facing surface. Routes assume the request
// passed through auth.RequireSession AND a future admin-role middleware
// (Phase 9). Until the role check lands, any authenticated user can reach
// these endpoints — operationally fine on a single-tenant deploy.
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

// Mount registers the routes onto r at /admin/review/.
func (h *Handler) Mount(r chi.Router) {
	r.Route("/admin/review", func(r chi.Router) {
		r.Get("/queue", h.queue)
		r.Post("/{item_id}/accept", h.accept)
		r.Post("/{item_id}/reject", h.reject)
		r.Post("/{item_id}/retire", h.retire)
	})
}

func (h *Handler) queue(w http.ResponseWriter, r *http.Request) {
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	res, err := h.svc.Queue(r.Context(), limit, offset)
	if err != nil {
		h.logger.Error("queue", "err", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	writeJSON(w, http.StatusOK, res)
}

func (h *Handler) accept(w http.ResponseWriter, r *http.Request) { h.transition(w, r, h.svc.Accept) }
func (h *Handler) reject(w http.ResponseWriter, r *http.Request) { h.transition(w, r, h.svc.Reject) }
func (h *Handler) retire(w http.ResponseWriter, r *http.Request) { h.transition(w, r, h.svc.Retire) }

func (h *Handler) transition(w http.ResponseWriter, r *http.Request, fn func(ctx context.Context, id uuid.UUID) error) {
	id, err := uuid.Parse(chi.URLParam(r, "item_id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid item_id")
		return
	}
	if err := fn(r.Context(), id); err != nil {
		if errors.Is(err, ErrItemNotFound) {
			writeError(w, http.StatusNotFound, "item not found")
			return
		}
		h.logger.Error("transition", "err", err, "item", id)
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
