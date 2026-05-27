// Package idem mints Idempotency-Key values in the platform's canonical
// "idem_<ulid>" form.
//
// The SDK auto-generates a key for every POST and state-transition PATCH
// the workflow wrappers issue (per AGENTS.md §5.2) unless the caller
// overrides it with workflows.WithIdempotencyKey. Keeping the helper in an
// internal/ package means consumers cannot accidentally couple to its exact
// ID layout — that's a platform implementation detail.
package idem

import "github.com/oklog/ulid/v2"

// New returns a fresh "idem_<ulid>" key. Safe for concurrent use; ulid.Make
// is internally locked.
func New() string {
	return "idem_" + ulid.Make().String()
}
