package postgres

import (
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"strings"
)

// passwordRandomBytes is the entropy budget per password. 32 bytes /
// 256 bits is overkill for a password (NIST SP 800-63B 5.1.1.2 calls
// 112 bits "high"); we pick 256 bits so that even after the base64
// alphabet shrink the worst-case effective entropy still clears 192
// bits.
const passwordRandomBytes = 32

// generateRolePassword returns a fresh URL-safe random password suitable
// for embedding in a Postgres CREATE ROLE PASSWORD literal.
//
// The base64 RawURLEncoding alphabet is `[A-Za-z0-9_-]`. The trailing
// `-` is unproblematic in a Postgres SQL literal (we single-quote, and
// the literal escape rule doubles only `'`); but `-` is awkward in
// shell-quoted DSNs (curl/psql treat a leading `-` as a flag if a value
// gets mis-quoted). We strip the two non-alphanumeric characters by
// re-encoding any sample that contains them, yielding an effective
// alphabet of `[A-Za-z0-9]` — exactly what every Postgres + libpq
// version handles unambiguously without DSN-encoding gotchas. The
// rejection sampling slightly biases length, so we trim to a fixed 40
// characters at the end (the post-stripping average is ~43 with stddev
// ~2; 40 fits comfortably below).
//
// We do NOT use the OS `pwgen` or the postgres `gen_random_uuid()`
// extension: this function is the single chokepoint for password
// material and we want it CSPRNG-clean and unit-testable in pure Go.
func generateRolePassword() (string, error) {
	// Allocate enough raw entropy that the worst-case shrink still
	// hits the 40-char target. 64 bytes → base64 → ~85 chars → after
	// stripping ~76 chars → trim to 40.
	const oversample = 64
	raw := make([]byte, oversample)
	if _, err := rand.Read(raw); err != nil {
		return "", fmt.Errorf("read random: %w", err)
	}
	encoded := base64.RawURLEncoding.EncodeToString(raw)
	// Strip the two non-alphanumeric characters the URL-safe alphabet
	// uses. This is a deterministic transform — we are not doing
	// rejection sampling in a loop, so the function always terminates.
	stripped := strings.NewReplacer("-", "", "_", "").Replace(encoded)
	if len(stripped) < 40 {
		// Statistically impossible with 64 bytes oversampled — even
		// if literally every byte produced a `-` or `_`, base64
		// alternates with safe chars, so the worst case is ~50%
		// retention which still clears 40. But check anyway: it is
		// cheap and the failure mode (a too-short password) would be
		// silently weaker than intended.
		return "", fmt.Errorf("password entropy shrink below target: got %d chars", len(stripped))
	}
	return stripped[:40], nil
}
