package auth

import (
	"context"
	"net/http"

	"github.com/omarss/qudrat/internal/store"
)

// userCtxKey is intentionally unexported and zero-sized so other packages
// can't impersonate it via context.WithValue.
type userCtxKey struct{}

// RequireSession returns middleware that resolves the session cookie to a
// user and attaches it to the request context. Requests with no cookie or
// an invalid token get 401 immediately.
//
// Pass cookieName, not the whole CookieConfig — the middleware only reads
// the cookie value.
func RequireSession(s *SessionService, cookieName string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			c, err := r.Cookie(cookieName)
			if err != nil {
				writeError(w, http.StatusUnauthorized, "unauthorized")
				return
			}
			res, err := s.Lookup(r.Context(), c.Value)
			if err != nil {
				writeError(w, http.StatusUnauthorized, "unauthorized")
				return
			}
			ctx := context.WithValue(r.Context(), userCtxKey{}, res.User)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// UserFrom returns the authenticated user attached to ctx by RequireSession,
// or false if the request didn't pass through it.
func UserFrom(ctx context.Context) (store.User, bool) {
	u, ok := ctx.Value(userCtxKey{}).(store.User)
	return u, ok
}
