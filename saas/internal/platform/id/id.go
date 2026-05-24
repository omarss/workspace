// Package id wraps oklog/ulid behind a small helper. Every public id in the
// platform is "<prefix>_<ulid>" — Crockford base32, 26 characters,
// lexicographically sortable by creation time.
package id

import "github.com/oklog/ulid/v2"

// New returns a new id of the form "<prefix>_<ulid>". ulid.Make is
// thread-safe (internal locked monotonic entropy), so callers do not need
// to coordinate.
func New(prefix string) string {
	return prefix + "_" + ulid.Make().String()
}
