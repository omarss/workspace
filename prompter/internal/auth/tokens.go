package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
)

// sessionTokenBytes sets the entropy of the cookie value. 32 bytes (256
// bits) keeps any meaningful collision risk well below the lifetime of
// every conceivable session table.
const sessionTokenBytes = 32

// GenerateSessionToken returns a fresh URL-safe random token suitable for a
// browser cookie. The plaintext leaves the server exactly once — the row
// stored in `sessions` carries only HashSessionToken(plaintext).
func GenerateSessionToken() (string, error) {
	var b [sessionTokenBytes]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", fmt.Errorf("rand.Read: %w", err)
	}
	return base64.RawURLEncoding.EncodeToString(b[:]), nil
}

// HashSessionToken returns the lower-case hex SHA-256 of the token.
//
// The hash is what we look up in `sessions.refresh_hash`. SHA-256 is fine
// here (vs bcrypt) because the input has 256 bits of entropy: nothing to
// brute-force, and constant-time UNIQUE lookup beats a per-row bcrypt scan.
func HashSessionToken(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}
