package problem

import (
	"errors"
	"net/http"

	"github.com/omarss/saas/internal/platform/auth"
)

// FromError translates a domain error into a Problem with the appropriate
// status + type URI. Returns ok=false for unknown errors — the caller logs
// the original error and returns a generic 500 problem.
//
// Handlers SHOULD NOT call http.Error directly. Anti-pattern guards in the
// Phase 3 plan forbid bypassing this mapper because the catalogue is the
// source of truth for clients (RFC 9457).
func FromError(err error, instance string) (Problem, bool) {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance), true
	case errors.Is(err, auth.ErrCrossTenant):
		return New("cross-tenant-access-denied", "Cross-tenant access denied.", http.StatusForbidden, "", instance), true
	case errors.Is(err, auth.ErrMissingScope):
		return New("forbidden", "Caller lacks required scope.", http.StatusForbidden, "", instance), true
	case errors.Is(err, auth.ErrKeyRevoked):
		return New("api-key-revoked", "API key revoked.", http.StatusUnauthorized, "", instance), true
	case errors.Is(err, auth.ErrKeyExpired):
		return New("api-key-expired", "API key expired.", http.StatusUnauthorized, "", instance), true
	case errors.Is(err, auth.ErrIPNotAllowed):
		return New("ip-not-allowlisted", "Source IP not allowlisted for this key.", http.StatusForbidden, "", instance), true
	case errors.Is(err, auth.ErrDisabled):
		return New("forbidden", "Principal is disabled.", http.StatusForbidden, "", instance), true
	}
	return Problem{}, false
}
