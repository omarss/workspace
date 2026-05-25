//go:build prod

// In prod builds the mock middleware is a strict pass-through. No
// X-Mock-* header has any effect — that escape hatch is physically
// excluded from the binary by the build tag, not by a runtime
// SAAS_ENV check (defence in depth).

package operatorjwt

import "net/http"

// MockMiddleware is a no-op in prod builds.
func MockMiddleware(next http.Handler) http.Handler { return next }
