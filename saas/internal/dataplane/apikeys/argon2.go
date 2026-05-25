package apikeys

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"strings"

	"golang.org/x/crypto/argon2"
)

// argon2id parameters. Locked to OWASP 2024 minimums per
// docs/plans/mvp/01-foundations.md §15 and AGENTS.md §18.2.
//
// Do NOT lower these without an ADR and a re-hash plan. argon2id
// verifies are deliberately costly; the auth-path batching of candidate
// rows + the prefix-search HMAC pre-filter keep request latency tractable
// (at most a small handful of verifies per auth attempt).
const (
	argonTime    uint32 = 2
	argonMemory  uint32 = 19 * 1024 // 19 MiB
	argonThreads uint8  = 1
	argonKeyLen  uint32 = 32
	argonSaltLen        = 16
)

// argonVersion mirrors the constant from golang.org/x/crypto/argon2.
// Inlined so the PHC string is built from a stable value the tests can
// assert against without reaching into the upstream package internals.
const argonVersion = 19

// HashSecret produces an argon2id PHC string of plaintext under the
// pinned parameters. Each call mints a fresh 16-byte salt from
// crypto/rand.
//
// Returned format:
//
//	$argon2id$v=19$m=19456,t=2,p=1$<b64 salt>$<b64 hash>
//
// where <b64 …> is base64.RawStdEncoding (PHC standard).
func HashSecret(plaintext string) (string, error) {
	if plaintext == "" {
		return "", fmt.Errorf("%w: empty plaintext", ErrInvalidInput)
	}
	salt := make([]byte, argonSaltLen)
	if _, err := rand.Read(salt); err != nil {
		return "", fmt.Errorf("apikeys: rand salt: %w", err)
	}
	hash := argon2.IDKey([]byte(plaintext), salt, argonTime, argonMemory, argonThreads, argonKeyLen)
	return encodePHC(salt, hash), nil
}

// VerifySecret returns true when plaintext hashes to the same key under
// the parameters parsed from phc. Constant-time compare keeps the
// verify path resistant to timing analysis.
//
// Errors are returned only for malformed PHC strings (operator bug, not
// caller bug); a mismatched hash returns (false, nil).
func VerifySecret(plaintext, phc string) (bool, error) {
	params, salt, expected, err := decodePHC(phc)
	if err != nil {
		return false, err
	}
	// keyLen is the length of the persisted hash; pinned to fit
	// uint32 — argon2id PHC hashes are at most a few hundred bytes,
	// never close to 2^32. The explicit cast keeps the static
	// analyser happy without changing behaviour.
	keyLen := len(expected)
	if keyLen < 0 || keyLen > int(^uint32(0)) {
		return false, fmt.Errorf("apikeys: PHC hash length out of range")
	}
	got := argon2.IDKey(
		[]byte(plaintext),
		salt,
		params.Time, params.Memory, params.Threads, uint32(keyLen),
	)
	if subtle.ConstantTimeCompare(got, expected) == 1 {
		return true, nil
	}
	return false, nil
}

// PHCParams is the parsed parameter triple from an argon2id PHC
// string. Exposed only to the verifier path; not part of the public
// module surface.
type PHCParams struct {
	Memory  uint32
	Time    uint32
	Threads uint8
}

func encodePHC(salt, hash []byte) string {
	return fmt.Sprintf(
		"$argon2id$v=%d$m=%d,t=%d,p=%d$%s$%s",
		argonVersion,
		argonMemory, argonTime, argonThreads,
		base64.RawStdEncoding.EncodeToString(salt),
		base64.RawStdEncoding.EncodeToString(hash),
	)
}

// decodePHC parses the canonical argon2id PHC format. We hand-roll
// the parser (rather than depending on a third-party PHC library) so
// the ~30 LoC stays auditable and matches docs/plans/mvp/01-foundations.md
// §15 verbatim. The parser is strict — any unknown variant, wrong
// version, or shape mismatch is an error.
func decodePHC(phc string) (PHCParams, []byte, []byte, error) {
	// Expected shape: $argon2id$v=19$m=...,t=...,p=...$<b64 salt>$<b64 hash>
	if !strings.HasPrefix(phc, "$argon2id$") {
		return PHCParams{}, nil, nil, fmt.Errorf("apikeys: invalid PHC variant")
	}
	parts := strings.Split(phc, "$")
	// "" "argon2id" "v=19" "m=..,t=..,p=.." "<salt>" "<hash>"
	if len(parts) != 6 {
		return PHCParams{}, nil, nil, fmt.Errorf("apikeys: invalid PHC shape")
	}
	if !strings.HasPrefix(parts[2], "v=") {
		return PHCParams{}, nil, nil, fmt.Errorf("apikeys: PHC missing version")
	}
	var v int
	if _, err := fmt.Sscanf(parts[2], "v=%d", &v); err != nil {
		return PHCParams{}, nil, nil, fmt.Errorf("apikeys: PHC version: %w", err)
	}
	if v != argonVersion {
		return PHCParams{}, nil, nil, fmt.Errorf("apikeys: unsupported PHC version %d", v)
	}
	var params PHCParams
	var threadsTmp uint32
	if _, err := fmt.Sscanf(parts[3], "m=%d,t=%d,p=%d", &params.Memory, &params.Time, &threadsTmp); err != nil {
		return PHCParams{}, nil, nil, fmt.Errorf("apikeys: PHC params: %w", err)
	}
	if threadsTmp > 255 {
		return PHCParams{}, nil, nil, fmt.Errorf("apikeys: PHC threads overflow")
	}
	params.Threads = uint8(threadsTmp)
	salt, err := base64.RawStdEncoding.DecodeString(parts[4])
	if err != nil {
		return PHCParams{}, nil, nil, fmt.Errorf("apikeys: PHC salt: %w", err)
	}
	hash, err := base64.RawStdEncoding.DecodeString(parts[5])
	if err != nil {
		return PHCParams{}, nil, nil, fmt.Errorf("apikeys: PHC hash: %w", err)
	}
	return params, salt, hash, nil
}

// ErrPHC is the umbrella sentinel for PHC parse failures. Callers that
// want a single check use errors.Is(err, ErrPHC); the wrapper messages
// above use fmt.Errorf without %w so VerifySecret surfaces the literal
// shape mismatch to logs without claiming a sentinel hit. Tests rely on
// the public error string staying stable enough to assert on.
var ErrPHC = errors.New("apikeys: malformed PHC")
