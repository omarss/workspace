// Package apikey generates, hashes, and verifies tenant API keys.
//
// Token shape: "ivr_<kid>.<secret>"
//
//   - kid: 12 base32 chars over 7 random bytes (no padding); public, used as
//     the database lookup index for the row holding the hashed secret.
//   - secret: 43 base64-url chars over 32 random bytes; the bearer credential.
//     Stored only as an Argon2id PHC string in the database.
//
// We deliberately persist the PHC string and not just the digest, so that
// algorithm parameters can evolve without a global rotation: a verifier
// reads the params from the stored hash, rederives, and compares.
package apikey

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/base32"
	"encoding/base64"
	"errors"
	"fmt"
	"math"
	"strings"

	"golang.org/x/crypto/argon2"
)

const (
	prefix         = "ivr_"
	kidRandomBytes = 7  // -> 12 base32 chars (no padding)
	kidEncodedLen  = 12 // computed from kidRandomBytes; kept here for SplitToken validation
	secretBytes    = 32 // -> 43 base64-url chars (no padding)

	// OWASP 2024 "interactive" Argon2id recommendation, scaled for our
	// laptop k3s; revisit after load testing.
	argonTime    = 3
	argonMem     = 64 * 1024 // KiB = 64 MiB
	argonThreads = 2
	argonKeyLen  = 32
	saltLen      = 16
)

var (
	kidEncoding    = base32.StdEncoding.WithPadding(base32.NoPadding)
	secretEncoding = base64.RawURLEncoding
)

// Sentinel errors. Callers should branch on errors.Is.
var (
	ErrEmptySecret    = errors.New("apikey: empty secret")
	ErrMalformedToken = errors.New("apikey: malformed token")
	ErrMalformedHash  = errors.New("apikey: malformed hash")
)

// APIKey is a freshly generated key. Secret is in plaintext exactly once,
// at the moment of generation, and must be returned to the caller and never
// persisted in this form.
type APIKey struct {
	KID    string
	Secret string
	Token  string // KID + "." + Secret
}

// Generate produces a new key with cryptographically random KID and Secret.
func Generate() (APIKey, error) {
	kidRaw := make([]byte, kidRandomBytes)
	if _, err := rand.Read(kidRaw); err != nil {
		return APIKey{}, fmt.Errorf("apikey: rand kid: %w", err)
	}
	secretRaw := make([]byte, secretBytes)
	if _, err := rand.Read(secretRaw); err != nil {
		return APIKey{}, fmt.Errorf("apikey: rand secret: %w", err)
	}
	kid := prefix + kidEncoding.EncodeToString(kidRaw)
	secret := secretEncoding.EncodeToString(secretRaw)
	return APIKey{KID: kid, Secret: secret, Token: kid + "." + secret}, nil
}

// Hash returns the PHC-formatted Argon2id hash of secret with a fresh salt.
func Hash(secret string) (string, error) {
	if secret == "" {
		return "", ErrEmptySecret
	}
	salt := make([]byte, saltLen)
	if _, err := rand.Read(salt); err != nil {
		return "", fmt.Errorf("apikey: rand salt: %w", err)
	}
	key := argon2.IDKey([]byte(secret), salt, argonTime, argonMem, argonThreads, argonKeyLen)
	return fmt.Sprintf(
		"$argon2id$v=%d$m=%d,t=%d,p=%d$%s$%s",
		argon2.Version, argonMem, argonTime, argonThreads,
		base64.RawStdEncoding.EncodeToString(salt),
		base64.RawStdEncoding.EncodeToString(key),
	), nil
}

// Verify constant-time-compares the supplied secret against a PHC-formatted
// stored hash. Returns (false, nil) for a mismatch on a well-formed hash,
// and (false, ErrMalformedHash) for a hash we can't parse.
func Verify(secret, encoded string) (bool, error) {
	parts := strings.Split(encoded, "$")
	if len(parts) != 6 || parts[0] != "" || parts[1] != "argon2id" {
		return false, ErrMalformedHash
	}
	var version int
	if _, err := fmt.Sscanf(parts[2], "v=%d", &version); err != nil || version != argon2.Version {
		return false, ErrMalformedHash
	}
	var mem, time, threads int
	if _, err := fmt.Sscanf(parts[3], "m=%d,t=%d,p=%d", &mem, &time, &threads); err != nil {
		return false, ErrMalformedHash
	}
	if mem <= 0 || time <= 0 || threads <= 0 ||
		mem > math.MaxUint32 || time > math.MaxUint32 || threads > math.MaxUint8 {
		return false, ErrMalformedHash
	}
	salt, err := base64.RawStdEncoding.DecodeString(parts[4])
	if err != nil || len(salt) == 0 {
		return false, ErrMalformedHash
	}
	expected, err := base64.RawStdEncoding.DecodeString(parts[5])
	if err != nil || len(expected) == 0 {
		return false, ErrMalformedHash
	}
	if len(expected) > math.MaxUint32 {
		return false, ErrMalformedHash
	}
	derived := argon2.IDKey([]byte(secret), salt, uint32(time), uint32(mem), uint8(threads), uint32(len(expected))) //nolint:gosec // bounds checked above
	return subtle.ConstantTimeCompare(derived, expected) == 1, nil
}

// SplitToken splits a "ivr_<kid>.<secret>" token without verifying the secret.
// Used at the auth middleware layer to look up the row by KID first.
func SplitToken(token string) (kid, secret string, err error) {
	if !strings.HasPrefix(token, prefix) {
		return "", "", ErrMalformedToken
	}
	parts := strings.Split(token, ".")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return "", "", ErrMalformedToken
	}
	if len(parts[0]) != len(prefix)+kidEncodedLen {
		return "", "", ErrMalformedToken
	}
	return parts[0], parts[1], nil
}
