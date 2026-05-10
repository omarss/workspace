package items

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/omarss/qudrat/internal/auth"
)

// Handler exposes the item-bank HTTP surface. All routes assume the request
// already passed through auth.RequireSession — handlers panic-free on a
// missing user via UserFrom's `ok` check returning a clean 401.
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

// Mount registers the routes onto r. The caller decides the prefix
// (typically /api, behind RequireSession).
func (h *Handler) Mount(r chi.Router) {
	r.Get("/sessions/quick-boost", h.quickBoost)
	r.Post("/attempts", h.submitAttempt)
	r.Get("/me/history", h.history)
	r.Get("/me/mastery", h.mastery)
}

// quickBoost: GET /sessions/quick-boost?count=5&exam_type=qudurat&section=quantitative&topic=…
func (h *Handler) quickBoost(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	q := r.URL.Query()
	count, _ := strconv.Atoi(q.Get("count"))
	res, err := h.svc.QuickBoost(r.Context(), QuickBoostParams{
		UserID:   user.ID,
		Count:    count,
		ExamType: q.Get("exam_type"),
		Section:  q.Get("section"),
		Topic:    q.Get("topic"),
	})
	if err != nil {
		switch {
		case errors.Is(err, ErrNoQuestionsForQuery):
			writeError(w, http.StatusNotFound, "no unanswered questions match the filter")
		default:
			h.logger.Error("quick-boost", "err", err, "user", user.ID)
			writeError(w, http.StatusInternalServerError, "internal error")
		}
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": res})
}

type attemptReq struct {
	ItemID      uuid.UUID `json:"item_id"`
	ChoiceKey   string    `json:"choice_key"`
	TimeTakenMS int       `json:"time_taken_ms"`
	HintUsed    bool      `json:"hint_used"`
}

// submitAttempt: POST /attempts
func (h *Handler) submitAttempt(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	var req attemptReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	res, err := h.svc.SubmitAttempt(r.Context(), AttemptInput{
		UserID:      user.ID,
		ItemID:      req.ItemID,
		ChoiceKey:   req.ChoiceKey,
		TimeTakenMS: req.TimeTakenMS,
		HintUsed:    req.HintUsed,
	})
	if err != nil {
		switch {
		case errors.Is(err, ErrItemNotFound):
			writeError(w, http.StatusNotFound, "item not found")
		case errors.Is(err, ErrInvalidChoice):
			writeError(w, http.StatusBadRequest, "choice_key must be A, B, C, or D")
		default:
			h.logger.Error("submit attempt", "err", err, "user", user.ID, "item", req.ItemID)
			writeError(w, http.StatusInternalServerError, "internal error")
		}
		return
	}
	writeJSON(w, http.StatusOK, res)
}

// history: GET /me/history?limit=20
func (h *Handler) history(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	res, err := h.svc.History(r.Context(), user.ID, limit)
	if err != nil {
		h.logger.Error("history", "err", err, "user", user.ID)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"history": res})
}

// mastery: GET /me/mastery?limit=50
func (h *Handler) mastery(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	res, err := h.svc.MasterySummary(r.Context(), user.ID, limit)
	if err != nil {
		h.logger.Error("mastery", "err", err, "user", user.ID)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"mastery": res})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
