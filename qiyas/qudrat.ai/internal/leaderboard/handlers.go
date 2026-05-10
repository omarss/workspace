package leaderboard

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"

	"github.com/omarss/qudrat/internal/auth"
)

// Handler exposes leaderboard reads + the user-facing opt-in/nickname
// writes. Mount under RequireSession.
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

// Mount registers the routes.
func (h *Handler) Mount(r chi.Router) {
	r.Get("/leaderboards/mastery", h.mastery)
	r.Get("/leaderboards/improvement", h.improvement)
	r.Put("/me/leaderboard", h.setOptIn)
	r.Put("/me/nickname", h.setNickname)
}

func (h *Handler) mastery(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	minAttempts, _ := strconv.Atoi(q.Get("min_attempts"))
	limit, _ := strconv.Atoi(q.Get("limit"))
	res, err := h.svc.Mastery(r.Context(), q.Get("exam_type"), minAttempts, limit)
	if err != nil {
		h.logger.Error("leaderboard mastery", "err", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"entries": res})
}

func (h *Handler) improvement(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	minAttempts, _ := strconv.Atoi(q.Get("min_attempts"))
	limit, _ := strconv.Atoi(q.Get("limit"))
	res, err := h.svc.Improvement(r.Context(), minAttempts, limit)
	if err != nil {
		h.logger.Error("leaderboard improvement", "err", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"entries": res})
}

type optInReq struct {
	OptIn bool `json:"opt_in"`
}

func (h *Handler) setOptIn(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	var req optInReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if err := h.svc.SetOptIn(r.Context(), user.ID, req.OptIn); err != nil {
		h.logger.Error("set opt-in", "err", err, "user", user.ID)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

type nicknameReq struct {
	Nickname string `json:"nickname"`
}

func (h *Handler) setNickname(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	var req nicknameReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if err := h.svc.SetNickname(r.Context(), user.ID, req.Nickname); err != nil {
		h.logger.Error("set nickname", "err", err, "user", user.ID)
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
