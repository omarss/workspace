package parent

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/omarss/qudrat/internal/auth"
)

// Handler exposes the parent API. Mount under RequireSession.
type Handler struct {
	svc    *Service
	logger *slog.Logger
}

// NewHandler wires deps.
func NewHandler(svc *Service, logger *slog.Logger) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{svc: svc, logger: logger}
}

// Mount registers the routes.
func (h *Handler) Mount(r chi.Router) {
	r.Route("/parent", func(r chi.Router) {
		r.Post("/links", h.requestLink)
		r.Get("/children", h.children)
		r.Get("/children/{child_id}/summary", h.summary)
		r.Post("/links/{link_id}/accept", h.accept)
		r.Post("/links/{link_id}/revoke", h.revoke)
	})
}

type linkReq struct {
	Channel    string `json:"channel"`
	Identifier string `json:"identifier"`
}

func (h *Handler) requestLink(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	var req linkReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	link, err := h.svc.RequestLink(r.Context(), user.ID, req.Channel, req.Identifier)
	if err != nil {
		switch {
		case errors.Is(err, ErrChildNotFound):
			writeError(w, http.StatusNotFound, "child not found")
		case errors.Is(err, ErrSelfLink):
			writeError(w, http.StatusBadRequest, "cannot link to self")
		default:
			h.logger.Error("request link", "err", err, "user", user.ID)
			writeError(w, http.StatusInternalServerError, "internal error")
		}
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]any{
		"link_id":  link.ID,
		"child_id": link.ChildID,
		"status":   link.Status,
	})
}

func (h *Handler) children(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	res, err := h.svc.Children(r.Context(), user.ID)
	if err != nil {
		h.logger.Error("children", "err", err, "user", user.ID)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"children": res})
}

func (h *Handler) summary(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	childID, err := uuid.Parse(chi.URLParam(r, "child_id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid child_id")
		return
	}
	res, err := h.svc.Summary(r.Context(), user.ID, childID)
	if err != nil {
		switch {
		case errors.Is(err, ErrNoConsent):
			writeError(w, http.StatusForbidden, "child has not accepted the link")
		default:
			h.logger.Error("summary", "err", err)
			writeError(w, http.StatusInternalServerError, "internal error")
		}
		return
	}
	writeJSON(w, http.StatusOK, res)
}

func (h *Handler) accept(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	linkID, err := uuid.Parse(chi.URLParam(r, "link_id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid link_id")
		return
	}
	if err := h.svc.Accept(r.Context(), linkID, user.ID); err != nil {
		h.logger.Error("accept", "err", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) revoke(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFrom(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	linkID, err := uuid.Parse(chi.URLParam(r, "link_id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid link_id")
		return
	}
	if err := h.svc.Revoke(r.Context(), linkID, user.ID); err != nil {
		h.logger.Error("revoke", "err", err)
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
