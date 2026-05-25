package apikeys

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"errors"
	"sync"

	platformcrypto "github.com/omarss/saas/internal/platform/crypto"
)

// PrefixIndexer wraps the per-deployment HMAC key + the platform
// Encryptor / Decryptor to produce the two prefix-lookup columns: the
// indexed HMAC bucket and the envelope-encrypted defence-in-depth
// envelope (ADR 008).
//
// The HMAC key lives in OpenBao KV at
// secret/data/<deployment_id>/api_keys/prefix_hmac_key under the field
// "key" (raw bytes encoded as a string). The KeyLoader interface lets
// tests inject a static key without reaching for the bao client.
type PrefixIndexer struct {
	enc          platformcrypto.Encryptor
	dec          platformcrypto.Decryptor
	deploymentID string
	loader       KeyLoader

	mu     sync.Mutex
	cached map[string][]byte // deployment_id -> raw key bytes
}

// KeyLoader sources the per-deployment HMAC key. The production
// implementation reads from OpenBao KV; tests substitute a static
// loader. The interface lives here so consumers can swap in fakes
// without depending on the bao client.
type KeyLoader interface {
	LoadHMACKey(ctx context.Context, deploymentID string) ([]byte, error)
}

// KeyLoaderFunc adapts a function into a KeyLoader. Tests typically
// pass `KeyLoaderFunc(func(...) { return staticKey, nil })`.
type KeyLoaderFunc func(ctx context.Context, deploymentID string) ([]byte, error)

// LoadHMACKey implements KeyLoader.
func (f KeyLoaderFunc) LoadHMACKey(ctx context.Context, deploymentID string) ([]byte, error) {
	return f(ctx, deploymentID)
}

// NewPrefixIndexer constructs an indexer bound to a deployment id. The
// encryptor + decryptor are typically the same EnvelopeAdapter used by
// other modules. The loader is the persistent key source.
func NewPrefixIndexer(deploymentID string, enc platformcrypto.Encryptor, dec platformcrypto.Decryptor, loader KeyLoader) *PrefixIndexer {
	return &PrefixIndexer{
		enc:          enc,
		dec:          dec,
		deploymentID: deploymentID,
		loader:       loader,
		cached:       map[string][]byte{},
	}
}

// IndexHash returns HMAC-SHA256(per-deployment key, prefix). Returns
// ErrIndexerKeyMissing when the loader cannot supply a key — callers
// fail closed on this branch.
func (p *PrefixIndexer) IndexHash(ctx context.Context, prefix string) ([]byte, error) {
	key, err := p.keyFor(ctx, p.deploymentID)
	if err != nil {
		return nil, err
	}
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(prefix))
	return mac.Sum(nil), nil
}

// WrapEnvelope produces the envelope-encrypted form of an HMAC bucket
// for storage in the prefix_lookup_envelope column. AAD format:
//
//	deployment_id|apikey|<api_key_id>|prefix_lookup
//
// — matches the CONVENTIONS.md §10.1 strict-mode walker shape so a
// row-swap attack across api_key rows fails the AEAD authentication
// tag check.
func (p *PrefixIndexer) WrapEnvelope(ctx context.Context, apiKeyID string, hash []byte) (LookupEnvelope, error) {
	aad := platformcrypto.FieldAAD(p.deploymentID, "apikey", apiKeyID, "prefix_lookup")
	env, err := p.enc.EncryptField(ctx, p.deploymentID, hash, aad)
	if err != nil {
		return LookupEnvelope{}, err
	}
	return LookupEnvelope{
		Ciphertext: env.Ciphertext,
		WrappedDEK: env.WrappedDEK,
		Nonce:      env.Nonce,
		KID:        env.KID,
		KeyVersion: env.KeyVersion,
	}, nil
}

// VerifyEnvelope decrypts the envelope and constant-time-compares the
// plaintext against expected. Returns true on a match. The decryptor
// short-circuits with envelope.ErrKidMismatch before any OpenBao
// round-trip if the row's kid does not equal the deployment id — layer
// 5 of the eight-layer tenant invariant.
//
// The function is the linchpin of the auth-path defence-in-depth: even
// if an attacker stole the HMAC key and forged a `prefix_lookup_hash`
// match, the envelope decrypt fails without the per-deployment Transit
// key.
func (p *PrefixIndexer) VerifyEnvelope(ctx context.Context, apiKeyID string, env LookupEnvelope, expected []byte) (bool, error) {
	if env.IsZero() {
		return false, nil
	}
	aad := platformcrypto.FieldAAD(p.deploymentID, "apikey", apiKeyID, "prefix_lookup")
	plaintext, err := p.dec.DecryptField(ctx, platformcrypto.Envelope{
		Ciphertext: env.Ciphertext,
		WrappedDEK: env.WrappedDEK,
		Nonce:      env.Nonce,
		Algo:       "aes-256-gcm",
		KID:        env.KID,
		KeyVersion: env.KeyVersion,
	}, p.deploymentID, aad)
	if err != nil {
		return false, err
	}
	if subtle.ConstantTimeCompare(plaintext, expected) == 1 {
		return true, nil
	}
	return false, nil
}

func (p *PrefixIndexer) keyFor(ctx context.Context, deploymentID string) ([]byte, error) {
	p.mu.Lock()
	if k, ok := p.cached[deploymentID]; ok {
		p.mu.Unlock()
		return k, nil
	}
	p.mu.Unlock()

	if p.loader == nil {
		return nil, ErrIndexerKeyMissing
	}
	key, err := p.loader.LoadHMACKey(ctx, deploymentID)
	if err != nil {
		return nil, err
	}
	if len(key) < 16 {
		return nil, ErrIndexerKeyMissing
	}
	p.mu.Lock()
	p.cached[deploymentID] = key
	p.mu.Unlock()
	return key, nil
}

// ErrIndexerKeyMissing is returned when the per-deployment HMAC key
// cannot be loaded (loader nil, missing KV entry, or insufficient
// length). Callers MUST fail closed.
var ErrIndexerKeyMissing = errors.New("apikeys: prefix-indexer HMAC key not available")

// BaoKVKeyLoader implements KeyLoader against a KV v2 store. The
// expected layout matches the identity HMAC pattern
// (HMACEmailHasher): `key` field at
// secret/data/<deployment_id>/api_keys/prefix_hmac_key. Stored value is
// raw bytes encoded as a string (typically hex / b64). The loader does
// not decode — the caller of NewSecret stored whatever shape the
// operator chose; we treat the bytes as opaque HMAC key material.
type BaoKVKeyLoader struct {
	KV BaoKVClient
}

// BaoKVClient is the narrow interface BaoKVKeyLoader needs from the
// envelope client; declared here so the apikeys package doesn't
// directly import the envelope subpackage.
type BaoKVClient interface {
	KVGet(ctx context.Context, deploymentID, path string) (map[string]any, error)
}

// LoadHMACKey reads the per-deployment HMAC key from KV v2. Returns
// ErrIndexerKeyMissing when the field is absent.
func (b *BaoKVKeyLoader) LoadHMACKey(ctx context.Context, deploymentID string) ([]byte, error) {
	if b == nil || b.KV == nil {
		return nil, ErrIndexerKeyMissing
	}
	data, err := b.KV.KVGet(ctx, deploymentID, "api_keys/prefix_hmac_key")
	if err != nil {
		return nil, err
	}
	raw, ok := data["key"].(string)
	if !ok || raw == "" {
		return nil, ErrIndexerKeyMissing
	}
	return []byte(raw), nil
}

// StaticKeyLoader is a fixed-key loader for tests + local dev with
// SAAS_OPENBAO_DISABLED=1. Production MUST use BaoKVKeyLoader with a
// per-deployment KV entry.
type StaticKeyLoader struct{ Key []byte }

// LoadHMACKey returns the static key.
func (s *StaticKeyLoader) LoadHMACKey(_ context.Context, _ string) ([]byte, error) {
	if len(s.Key) < 16 {
		return nil, ErrIndexerKeyMissing
	}
	return s.Key, nil
}
