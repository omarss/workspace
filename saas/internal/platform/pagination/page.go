// Package pagination provides the Page[T] envelope every list endpoint
// returns. It pairs with internal/platform/cursor for the opaque keyset
// cursor; CONVENTIONS.md documents how to wire both into a new handler.
//
// The Page envelope renders to JSON as:
//
//	{ "data": [...], "pagination": { "next_cursor": "...", "has_more": true } }
//
// which mirrors the openapi/data-plane.yaml Pagination schema. Handlers
// translate Page[Domain] into the generated httpapi.<Resource>ListResponse
// type with a small Convert helper local to the module.
package pagination

// Page is a typed list envelope. Handlers materialise this from a
// service-layer return tuple (rows, hasMore) and then map domain rows into
// the API DTO before serialising.
type Page[T any] struct {
	Data       []T
	NextCursor string
	HasMore    bool
}

// DefaultLimit and MaxLimit mirror the OpenAPI parameters. 25 is the
// platform-wide default; 200 is the hard upper bound (AGENTS.md §5.3).
const (
	DefaultLimit = 25
	MaxLimit     = 200
)

// ClampLimit returns a sane page size — defaults to DefaultLimit, capped at
// MaxLimit. Negative / zero falls back to the default.
func ClampLimit(limit int) int {
	if limit <= 0 {
		return DefaultLimit
	}
	if limit > MaxLimit {
		return MaxLimit
	}
	return limit
}
