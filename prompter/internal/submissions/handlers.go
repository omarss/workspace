package submissions

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/omarss/prompter/internal/auth"
)

// Handler exposes the gameplay HTTP surface.
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

// Mount registers the routes. Caller wraps with auth.RequireSession.
func (h *Handler) Mount(r chi.Router) {
	r.Post("/", h.create)
	r.Get("/{id}", h.get)
}

type createReq struct {
	ChallengeID uuid.UUID `json:"challenge_id"`
	ModelSlug   string    `json:"model_slug"`
	Prompt      string    `json:"prompt"`
}

func (h *Handler) create(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	var req createReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	sub, err := h.svc.Submit(r.Context(), SubmitParams{
		UserID:      user.ID,
		ChallengeID: req.ChallengeID,
		ModelSlug:   req.ModelSlug,
		Prompt:      req.Prompt,
	})
	if err != nil {
		h.mapSubmitError(w, sub, err)
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]any{"submission": sub})
}

func (h *Handler) mapSubmitError(w http.ResponseWriter, sub Submission, err error) {
	switch {
	case errors.Is(err, ErrPromptEmpty):
		writeError(w, http.StatusBadRequest, "prompt is empty")
	case errors.Is(err, ErrChallengeNotFound):
		writeError(w, http.StatusNotFound, "challenge not found")
	case errors.Is(err, ErrModelNotFound):
		writeError(w, http.StatusBadRequest, "model not found")
	case errors.Is(err, ErrPromptOverlap):
		// 422 with the rejected submission so the client can show audit info.
		writeJSON(w, http.StatusUnprocessableEntity, map[string]any{
			"error":      "prompt overlaps target",
			"submission": sub,
		})
	default:
		h.logger.Error("submit", "err", err)
		writeError(w, http.StatusInternalServerError, "internal error")
	}
}

func (h *Handler) get(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	rawID := chi.URLParam(r, "id")
	id, err := uuid.Parse(rawID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid id")
		return
	}
	sub, err := h.svc.Get(r.Context(), id, user.ID)
	if err != nil {
		if errors.Is(err, ErrSubmissionMissing) {
			writeError(w, http.StatusNotFound, "not found")
			return
		}
		h.logger.Error("get submission", "err", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"submission": sub})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
