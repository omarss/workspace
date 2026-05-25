package apikeys

import (
	"crypto/rand"
	"encoding/base32"
	"errors"
	"fmt"
	"strings"
)

// Crockford base32 mirrors the ULID alphabet — base32hex with the
// confusable characters removed. The stdlib `encoding/base32` exposes
// the standard alphabet; we substitute the Crockford one and strip
// padding because the caller's bearer is fixed-length and we don't want
// `=` chars in the URL-safe surface area.
//
// Alphabet reference: https://www.crockford.com/base32.html
var crockfordEnc = base32.NewEncoding("0123456789ABCDEFGHJKMNPQRSTVWXYZ").WithPadding(base32.NoPadding)

// GeneratedSecret bundles the plaintext bearer + visible prefix +
// HMAC-input string. Callers receive this from NewSecret at create /
// rotate time, hash the Plaintext, persist Prefix + the envelope of
// the prefix HMAC, and return Plaintext to the caller exactly once.
type GeneratedSecret struct {
	// Plaintext is the full bearer the caller will send on the
	// Authorization header. Shape: `<env>_<prefix-rand>_<full-rand>`.
	// Length: 4 (live) + 1 + 8 + 1 + 32 = 46 chars for live, or 5 + 1
	// + 8 + 1 + 32 = 47 for test.
	Plaintext string
	// Prefix is the visible portion stored on the row. Shape:
	// `<env>_<prefix-rand>` — no trailing underscore, no random
	// portion. Example: "live_AX9BC7D3".
	Prefix string
}

// NewSecret mints a fresh bearer + its visible prefix using crypto/rand
// and Crockford base32. Environment defaults to live when empty.
//
// Why Crockford base32 (not hex or url-safe base64):
//
//   - 5 bits per char → high entropy density (32 chars ≈ 160 bits).
//   - Removes 0/O, 1/I/L confusables — humans copy-pasting bearers
//     from a one-time view see fewer transcription bugs.
//   - Stdlib-supported encoder.
//
// crypto/rand.Read is documented to never return an error on Linux
// (uses getrandom(2)); we still bubble up the error to be honest about
// the contract.
func NewSecret(env Environment) (GeneratedSecret, error) {
	if env == "" {
		env = EnvironmentLive
	}
	switch env {
	case EnvironmentLive, EnvironmentTest:
		// ok
	default:
		return GeneratedSecret{}, fmt.Errorf("%w: unknown environment %q", ErrInvalidInput, env)
	}

	// 8 Crockford base32 chars = 5 bytes of entropy.
	preBytes := make([]byte, prefixRandomBytes)
	if _, err := rand.Read(preBytes); err != nil {
		return GeneratedSecret{}, fmt.Errorf("apikeys: rand prefix: %w", err)
	}
	// 32 chars = 20 bytes of entropy.
	randBytes := make([]byte, secretRandomBytes)
	if _, err := rand.Read(randBytes); err != nil {
		return GeneratedSecret{}, fmt.Errorf("apikeys: rand secret: %w", err)
	}

	preStr := crockfordEnc.EncodeToString(preBytes)
	randStr := crockfordEnc.EncodeToString(randBytes)

	prefix := string(env) + "_" + preStr
	plaintext := prefix + "_" + randStr
	return GeneratedSecret{Plaintext: plaintext, Prefix: prefix}, nil
}

// Constants kept private because callers should treat the field width
// (PrefixRandomLen / SecretRandomLen) as the source of truth.
const (
	prefixRandomBytes = 5  // 5 bytes * 8 / 5 = 8 chars
	secretRandomBytes = 20 // 20 bytes * 8 / 5 = 32 chars
)

// ParseBearer splits a presented bearer into (env, prefix, secret).
// Returns ErrBearerMalformed when the shape does not match the schema.
//
// Shape: `<env>_<8 chars>_<32 chars>`.
//
//	env    ∈ {"live","test"}
//	prefix uppercase Crockford base32, length PrefixRandomLen
//	secret uppercase Crockford base32, length SecretRandomLen
//
// The function does NOT validate the alphabet of the chars (a forged
// bearer with arbitrary chars still fails the argon verify); it only
// checks lengths so the auth path can short-circuit obvious garbage
// before touching the DB.
func ParseBearer(bearer string) (env Environment, visiblePrefix, secret string, err error) {
	parts := strings.SplitN(bearer, "_", 3)
	if len(parts) != 3 {
		return "", "", "", ErrBearerMalformed
	}
	envPart, prePart, secPart := parts[0], parts[1], parts[2]
	switch Environment(envPart) {
	case EnvironmentLive, EnvironmentTest:
		// ok
	default:
		return "", "", "", ErrBearerMalformed
	}
	if len(prePart) != PrefixRandomLen {
		return "", "", "", ErrBearerMalformed
	}
	if len(secPart) != SecretRandomLen {
		return "", "", "", ErrBearerMalformed
	}
	return Environment(envPart), envPart + "_" + prePart, bearer, nil
}

// ValidateScope returns ErrInvalidInput when a scope string does not
// match the resource_type.action shape required by the OpenAPI schema
// pattern. Centralised so handler + service share one validator.
func ValidateScope(scope string) error {
	if scope == "" {
		return fmt.Errorf("%w: empty scope", ErrInvalidInput)
	}
	dot := strings.IndexByte(scope, '.')
	if dot <= 0 || dot >= len(scope)-1 {
		return fmt.Errorf("%w: scope must be resource_type.action", ErrInvalidInput)
	}
	if !isLowerSnake(scope[:dot]) || !isLowerSnake(scope[dot+1:]) {
		return fmt.Errorf("%w: scope tokens must be [a-z_]+", ErrInvalidInput)
	}
	return nil
}

func isLowerSnake(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if (r < 'a' || r > 'z') && r != '_' {
			return false
		}
	}
	return true
}

// ErrNotEnoughEntropy is documented for completeness; reserved for a
// future hardening pass that derives randomness from a deterministic
// post-rotation seed (rotation is currently from crypto/rand, so this
// sentinel is unused today).
var ErrNotEnoughEntropy = errors.New("apikeys: insufficient entropy")
