//go:build unix

package nginx

import "syscall"

// setUmask wraps syscall.Umask for the umask round-trip test. Lives in a
// build-tagged file so non-Unix builds compile (no platform fallback —
// the test that needs this is itself unix-only by virtue of the file
// being tagged `unix` as well at the package level via this helper).
func setUmask(mask int) int { return syscall.Umask(mask) }
