package auth

import (
	"crypto/subtle"
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

// ExternalHandler exposes POST /auth/external for trusted bot-side callers.
// The endpoint is gated by a shared bearer token (BOT_AUTH_TOKEN env var).
type ExternalHandler struct {
	external *ExternalService
	session  *SessionService
	cookie   CookieConfig
	botToken string
	logger   *slog.Logger
}

// NewExternalHandler wires deps. botToken=="" disables the endpoint
// entirely — the route returns 503 so a misconfigured production deploy
// fails loudly instead of falling back to "no auth".
func NewExternalHandler(ext *ExternalService, session *SessionService, cookie CookieConfig, botToken string, logger *slog.Logger) *ExternalHandler {
	if logger == nil {
		logger = slog.Default()
	}
	return &ExternalHandler{external: ext, session: session, cookie: cookie, botToken: botToken, logger: logger}
}

// Mount registers the route.
func (h *ExternalHandler) Mount(r chi.Router) {
	r.Post("/auth/external", h.handle)
}

type externalReq struct {
	Channel    string `json:"channel"`
	ExternalID string `json:"external_id"`
}

type externalResp struct {
	UserID    uuid.UUID `json:"user_id"`
	Token     string    `json:"token"` // bearer/cookie value the bot caches per chat
	ExpiresAt string    `json:"expires_at"`
}

func (h *ExternalHandler) handle(w http.ResponseWriter, r *http.Request) {
	if h.botToken == "" {
		writeError(w, http.StatusServiceUnavailable, "external auth not configured")
		return
	}
	got := r.Header.Get("Authorization")
	expected := "Bearer " + h.botToken
	// Constant-time compare to avoid timing-based token discovery.
	if subtle.ConstantTimeCompare([]byte(got), []byte(expected)) != 1 {
		writeError(w, http.StatusUnauthorized, "invalid bot token")
		return
	}

	var req externalReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	user, err := h.external.ResolveOrCreate(r.Context(), req.Channel, req.ExternalID)
	if err != nil {
		h.logger.Error("external resolve", "err", err, "channel", req.Channel)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	token, expires, err := h.session.Create(r.Context(), user.ID, r.RemoteAddr, r.UserAgent())
	if err != nil {
		h.logger.Error("external session create", "err", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	writeJSON(w, http.StatusOK, externalResp{
		UserID:    user.ID,
		Token:     token,
		ExpiresAt: expires.Format("2006-01-02T15:04:05Z07:00"),
	})
}
