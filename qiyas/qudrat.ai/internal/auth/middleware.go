package auth

import (
	"context"
	"net/http"

	"github.com/omarss/qudrat/internal/store"
)

// userCtxKey is intentionally unexported and zero-sized so other packages
// can't impersonate it via context.WithValue.
type userCtxKey struct{}

// RequireSession returns middleware that resolves the session token to a
// user and attaches it to the request context. The token is read from
// either the session cookie OR a `Authorization: Bearer …` header — the
// header path is what the bot uses since it doesn't have a cookie store.
//
// Requests with neither, or an invalid token, get 401 immediately.
func RequireSession(s *SessionService, cookieName string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			token := bearerOrCookie(r, cookieName)
			if token == "" {
				writeError(w, http.StatusUnauthorized, "unauthorized")
				return
			}
			res, err := s.Lookup(r.Context(), token)
			if err != nil {
				writeError(w, http.StatusUnauthorized, "unauthorized")
				return
			}
			ctx := context.WithValue(r.Context(), userCtxKey{}, res.User)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// bearerOrCookie returns the session token from the Authorization header
// (Bearer scheme) if present, falling back to the cookie. Header wins so
// machine clients can override a stale cookie they may carry.
func bearerOrCookie(r *http.Request, cookieName string) string {
	if h := r.Header.Get("Authorization"); len(h) > 7 && (h[:7] == "Bearer " || h[:7] == "bearer ") {
		return h[7:]
	}
	if c, err := r.Cookie(cookieName); err == nil {
		return c.Value
	}
	return ""
}

// UserFrom returns the authenticated user attached to ctx by RequireSession,
// or false if the request didn't pass through it.
func UserFrom(ctx context.Context) (store.User, bool) {
	u, ok := ctx.Value(userCtxKey{}).(store.User)
	return u, ok
}
