//go:build prod

// File-level build tag: production binaries compile this no-op variant
// instead of middleware_mock.go. The mock header path is physically
// unreachable in `go build -tags prod` output. The real JWT-verifying
// middleware is wired by cmd/* binaries once Phase 5 ships it; this file
// only guarantees the mock path cannot leak into prod.

package auth

import "net/http"

// MockMiddleware is a compile-time no-op in prod builds — the X-Mock-*
// header path is absent from production binaries. Phase 5 plugs in the
// real JWT middleware ahead of this layer.
func MockMiddleware(next http.Handler) http.Handler { return next }
