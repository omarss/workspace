package auth

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/omarss/qudrat/internal/store"
)

// CookieConfig describes the session cookie attributes. Production sets
// Secure=true and Domain="qudrat.omarss.net"; local dev leaves both off.
type CookieConfig struct {
	Name     string
	Path     string
	Domain   string
	Secure   bool
	SameSite http.SameSite
	HTTPOnly bool
}

// Handler exposes the auth HTTP surface.
type Handler struct {
	otp     *OTPService
	session *SessionService
	cookie  CookieConfig
	logger  *slog.Logger
}

// NewHandler wires the dependencies. logger=nil falls back to slog.Default.
func NewHandler(otp *OTPService, session *SessionService, cookie CookieConfig, logger *slog.Logger) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{otp: otp, session: session, cookie: cookie, logger: logger}
}

// Mount registers the routes the auth flow owns onto r. The caller decides
// the prefix (typically /api).
func (h *Handler) Mount(r chi.Router) {
	r.Route("/auth", func(r chi.Router) {
		r.Post("/otp/start", h.otpStart)
		r.Post("/otp/verify", h.otpVerify)
		r.Post("/logout", h.logout)
	})
	r.Get("/me", h.me)
}

type startReq struct {
	Channel    string `json:"channel"`
	Identifier string `json:"identifier"`
}

type startResp struct {
	ChallengeID uuid.UUID `json:"challenge_id"`
	ExpiresAt   time.Time `json:"expires_at"`
}

func (h *Handler) otpStart(w http.ResponseWriter, r *http.Request) {
	var req startReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	res, err := h.otp.Start(r.Context(), StartParams{
		Channel:    req.Channel,
		Identifier: req.Identifier,
		IP:         r.RemoteAddr,
		UA:         r.UserAgent(),
	})
	if err != nil {
		h.mapStartError(w, err)
		return
	}
	writeJSON(w, http.StatusAccepted, startResp(res))
}

func (h *Handler) mapStartError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrInvalidChannel), errors.Is(err, ErrInvalidIdentifier):
		writeError(w, http.StatusBadRequest, err.Error())
	case errors.Is(err, ErrRateLimited):
		writeError(w, http.StatusTooManyRequests, "too many requests")
	case errors.Is(err, ErrProvider):
		writeError(w, http.StatusBadGateway, "provider error")
	default:
		h.logger.Error("otp start", "err", err)
		writeError(w, http.StatusInternalServerError, "internal error")
	}
}

type verifyReq struct {
	ChallengeID uuid.UUID `json:"challenge_id"`
	Code        string    `json:"code"`
}

type meResp struct {
	User userPublic `json:"user"`
}

// userPublic is the user view safe to return over the wire — no internal
// timestamps, no raw nullable types pgtype would expose.
type userPublic struct {
	ID       uuid.UUID `json:"id"`
	Email    *string   `json:"email,omitempty"`
	Phone    *string   `json:"phone,omitempty"`
	Nickname string    `json:"nickname"`
}

func toPublic(u store.User) userPublic {
	return userPublic{ID: u.ID, Email: u.Email, Phone: u.Phone, Nickname: u.Nickname}
}

func (h *Handler) otpVerify(w http.ResponseWriter, r *http.Request) {
	var req verifyReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	res, err := h.otp.Verify(r.Context(), req.ChallengeID, req.Code)
	if err != nil {
		h.mapVerifyError(w, err)
		return
	}
	token, expires, err := h.session.Create(r.Context(), res.User.ID, r.RemoteAddr, r.UserAgent())
	if err != nil {
		h.logger.Error("create session", "err", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	h.setCookie(w, token, expires)
	writeJSON(w, http.StatusOK, meResp{User: toPublic(res.User)})
}

func (h *Handler) mapVerifyError(w http.ResponseWriter, err error) {
	switch {
	// Collapse all "wrong code" reasons into a single 400 so the client
	// can't enumerate which step failed.
	case errors.Is(err, ErrChallengeNotFound),
		errors.Is(err, ErrChallengeExpired),
		errors.Is(err, ErrChallengeConsumed),
		errors.Is(err, ErrTooManyAttempts),
		errors.Is(err, ErrOTPMismatch):
		writeError(w, http.StatusBadRequest, "invalid code")
	case errors.Is(err, ErrInvalidChannel):
		writeError(w, http.StatusBadRequest, "invalid channel")
	case errors.Is(err, ErrProvider):
		writeError(w, http.StatusBadGateway, "provider error")
	default:
		h.logger.Error("otp verify", "err", err)
		writeError(w, http.StatusInternalServerError, "internal error")
	}
}

func (h *Handler) logout(w http.ResponseWriter, r *http.Request) {
	if c, err := r.Cookie(h.cookie.Name); err == nil {
		// Best-effort revocation; clear the cookie either way.
		_ = h.session.Revoke(r.Context(), c.Value)
	}
	h.clearCookie(w)
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) me(w http.ResponseWriter, r *http.Request) {
	token := bearerOrCookie(r, h.cookie.Name)
	if token == "" {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	res, err := h.session.Lookup(r.Context(), token)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	writeJSON(w, http.StatusOK, meResp{User: toPublic(res.User)})
}

func (h *Handler) setCookie(w http.ResponseWriter, value string, expires time.Time) {
	http.SetCookie(w, &http.Cookie{
		Name:     h.cookie.Name,
		Value:    value,
		Path:     h.cookie.Path,
		Domain:   h.cookie.Domain,
		Expires:  expires,
		Secure:   h.cookie.Secure,
		HttpOnly: h.cookie.HTTPOnly,
		SameSite: h.cookie.SameSite,
	})
}

func (h *Handler) clearCookie(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{
		Name:     h.cookie.Name,
		Value:    "",
		Path:     h.cookie.Path,
		Domain:   h.cookie.Domain,
		MaxAge:   -1,
		Secure:   h.cookie.Secure,
		HttpOnly: h.cookie.HTTPOnly,
		SameSite: h.cookie.SameSite,
	})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
