package crypto

import (
	"context"

	"github.com/omarss/saas/internal/platform/crypto/envelope"
)

// EnvelopeAdapter implements Encryptor by delegating to an envelope.Client.
// Use this at process startup to wire the OpenBao-backed Encryptor without
// leaking the bao API into every consumer of the crypto package.
//
// The adapter intentionally lives here (not in the envelope subpackage) so
// modules that depend on the Encryptor interface — which is most of the
// internal/ tree — never transitively import the bao client. That keeps
// build times sane and mock-driven unit tests fast.
type EnvelopeAdapter struct {
	Client *envelope.Client
}

// NewEnvelopeAdapter wires the OpenBao Encryptor. Pass the long-lived
// envelope.Client constructed at process startup.
func NewEnvelopeAdapter(c *envelope.Client) *EnvelopeAdapter {
	return &EnvelopeAdapter{Client: c}
}

// EncryptField implements the Encryptor interface. Calls envelope.Encrypt
// under the hood and copies the result into the parent package's Envelope
// shape so the walker doesn't need to import the subpackage.
func (a *EnvelopeAdapter) EncryptField(ctx context.Context, kid string, plaintext, aad []byte) (Envelope, error) {
	if a == nil || a.Client == nil {
		return Envelope{}, ErrNoEncryptor
	}
	out, err := a.Client.Encrypt(ctx, kid, plaintext, aad)
	if err != nil {
		return Envelope{}, err
	}
	return Envelope{
		Ciphertext: out.Ciphertext,
		WrappedDEK: out.WrappedDEK,
		Nonce:      out.Nonce,
		Algo:       out.Algo,
		KID:        out.KID,
		KeyVersion: out.KeyVersion,
	}, nil
}

// DecryptField is the symmetric helper. Callers that already hold an
// envelope.Client can call its Decrypt directly; this method exists for
// repository code paths that route through the Encryptor interface.
func (a *EnvelopeAdapter) DecryptField(ctx context.Context, env Envelope, expectedKid string, aad []byte) ([]byte, error) {
	if a == nil || a.Client == nil {
		return nil, ErrNoEncryptor
	}
	return a.Client.Decrypt(ctx, envelope.Envelope{
		Ciphertext: env.Ciphertext,
		WrappedDEK: env.WrappedDEK,
		Nonce:      env.Nonce,
		Algo:       env.Algo,
		KID:        env.KID,
		KeyVersion: env.KeyVersion,
	}, expectedKid, aad)
}
