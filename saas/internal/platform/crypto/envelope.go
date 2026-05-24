// Package crypto declares the envelope-encryption interface used by
// persistence-layer code. ADR 004 documents the x-pii → struct-tag →
// reflection-walker pipeline; Phase 4 (OpenBao integration) implements the
// Encryptor against OpenBao's transit/datakey + transit/decrypt endpoints.
//
// Phase 3 ships the interface + the reflection walker so module authors can
// write the call-site idiom today; the walker panics-via-error if invoked
// before an Encryptor is wired, so misuse is loud rather than silent.
package crypto

import "errors"

// Envelope carries the wrapped DEK + ciphertext + nonce + algorithm
// metadata produced by the OpenBao envelope-encryption flow. AGENTS.md
// §18.7 specifies the schema; the row binding (kid == deployment_id) is
// enforced by the persistence layer before decrypt.
type Envelope struct {
	// Ciphertext is the AES-GCM ciphertext of the plaintext value.
	Ciphertext []byte
	// WrappedDEK is the OpenBao-wrapped data encryption key, format
	// "vault:v<N>:<base64>". Phase 4 parses key version from this string.
	WrappedDEK string
	// Nonce is the 12-byte AES-GCM nonce.
	Nonce []byte
	// Algo records the algorithm name for forward compatibility
	// ("aes-256-gcm" today).
	Algo string
	// KID is the deployment-bound key id; persistence layer asserts
	// KID == ctx.DeploymentID before issuing the decrypt call (layer 5).
	KID string
	// KeyVersion is the transit key version extracted from WrappedDEK.
	KeyVersion int
}

// IsZero reports whether the envelope carries no encrypted payload. Empty
// envelopes happen when an optional PII column (e.g. User.Name) was never set
// on a Create or Update — the persistence layer skips empty envelopes
// instead of binding NULL columns to a zero-length ciphertext.
func (e Envelope) IsZero() bool {
	return e.WrappedDEK == "" && len(e.Ciphertext) == 0
}

// Errors returned by EncryptPIIFields.
var (
	// ErrNotPointer — caller passed a non-pointer or nil to EncryptPIIFields.
	ErrNotPointer = errors.New("crypto: EncryptPIIFields requires a non-nil pointer to a struct")
	// ErrNoEncryptor — no Encryptor wired yet. Phase 4 supplies the OpenBao
	// implementation; Phase 3 returns this for any actual encryption call so
	// missing wiring is loud.
	ErrNoEncryptor = errors.New("crypto: no encryptor wired (Phase 4 OpenBao integration not yet active)")
)
