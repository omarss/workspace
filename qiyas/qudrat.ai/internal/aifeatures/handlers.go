// Package aifeatures owns the LLM-powered surfaces from spec §3 / §23:
//
//   - Personalized explanation: rephrase the static `explanation` per the
//     learner's preferred style and most-recent error pattern.
//   - Photo question solving: extract a question from an uploaded image and
//     return an answer + explanation.
//
// Phase 10 lands the HTTP surface and event tracking; the actual LLM call
// is delegated to a vendor adapter that doesn't ship until the operator
// configures one. Without an adapter, every endpoint returns 501 Not
// Implemented — the routes exist so frontend work can mock against them.
//
// When the adapter lands, plug it into NewHandler via the optional
// constructor (added in a follow-up). The persistence side records every
// request as an event so usage is observable from day zero.
package aifeatures

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/omarss/qudrat/internal/auth"
	"github.com/omarss/qudrat/internal/events"
)

// Handler exposes the AI feature endpoints.
type Handler struct {
	events *events.Service
	logger *slog.Logger
}

// NewHandler wires deps. Without a real LLM provider this handler always
// reports 501 — but the events still fire so we can see the demand.
func NewHandler(ev *events.Service, logger *slog.Logger) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{events: ev, logger: logger}
}

// Mount registers the routes. Mount under RequireSession.
func (h *Handler) Mount(r chi.Router) {
	r.Post("/items/{item_id}/explain", h.explain)
	r.Post("/photo-question", h.photoQuestion)
}

type explainReq struct {
	Style string `json:"style"` // "concise" | "step_by_step" | "visual"
}

func (h *Handler) explain(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	itemID, err := uuid.Parse(chi.URLParam(r, "item_id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid item_id")
		return
	}
	var req explainReq
	_ = json.NewDecoder(r.Body).Decode(&req)
	h.events.Record(r.Context(), "ai_explanation_requested", &user.ID, &itemID, map[string]any{
		"style": req.Style,
	})
	writeError(w, http.StatusNotImplemented, "personalized explanations are not configured on this deploy")
}

func (h *Handler) photoQuestion(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	h.events.Record(r.Context(), "ai_photo_question_requested", &user.ID, nil, nil)
	writeError(w, http.StatusNotImplemented, "photo question solving is not configured on this deploy")
}

func writeError(w http.ResponseWriter, status int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
