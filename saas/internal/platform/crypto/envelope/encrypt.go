package envelope

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"runtime"
	"strconv"
	"strings"
)

// Envelope is the on-the-wire envelope produced by Encrypt and consumed by
// Decrypt. The persistence layer stores each field as its own column (see
// CONVENTIONS.md §10.x).
type Envelope struct {
	// Ciphertext is the AES-256-GCM ciphertext with the auth tag appended.
	Ciphertext []byte
	// WrappedDEK is the OpenBao-wrapped data encryption key, formatted as
	// "vault:v<N>:<b64>" (or "bao:v<N>:..." depending on engine config).
	WrappedDEK string
	// Nonce is the 12-byte AES-GCM nonce. Random per call; never reused.
	Nonce []byte
	// Algo records the algorithm name for forward compatibility. Today
	// always "aes-256-gcm".
	Algo string
	// KID is the deployment-bound key id. Decrypt verifies KID equals the
	// caller-supplied expected kid BEFORE issuing the OpenBao API call.
	KID string
	// KeyVersion is parsed from the WrappedDEK prefix at write time so the
	// rewrap walker can find rows behind the latest version.
	KeyVersion int
}

// Encrypt generates a fresh DEK via transit/datakey/plaintext/:kid, encrypts
// plaintext with AES-256-GCM under that DEK, and returns the envelope. The
// DEK plaintext is zeroed before the function returns.
//
// aad is bound into the AEAD tag — supplying a different aad at decrypt
// time causes the tag check to fail. Conventional shape:
//
//	aad = deployment_id || resource_type || resource_id
//
// Empty plaintext returns a zero Envelope without making the OpenBao call;
// callers should treat a zero envelope as "no value persisted".
func (c *Client) Encrypt(ctx context.Context, kid string, plaintext, aad []byte) (Envelope, error) {
	if err := validateKid(kid); err != nil {
		return Envelope{}, err
	}
	if len(plaintext) == 0 {
		return Envelope{}, nil
	}

	// Ask OpenBao for a 32-byte DEK + the same DEK wrapped against the
	// per-Deployment transit key. The "context" parameter is base64-encoded
	// only when the transit key was created with derived=true; we don't use
	// derived keys (the per-Deployment kid already provides isolation), so
	// we omit the context here. Adding it would require rebuilding the same
	// context at decrypt time, which is the same property the GCM AAD
	// already provides.
	sec, err := c.bao.Logical().WriteWithContext(ctx, "transit/datakey/plaintext/"+kid, map[string]any{
		"bits": 256,
	})
	if err != nil {
		return Envelope{}, fmt.Errorf("envelope: datakey: %w", err)
	}
	if sec == nil || sec.Data == nil {
		return Envelope{}, errors.New("envelope: datakey response was empty")
	}
	dekB64, _ := sec.Data["plaintext"].(string)
	wrapped, _ := sec.Data["ciphertext"].(string)
	if dekB64 == "" || wrapped == "" {
		return Envelope{}, errors.New("envelope: datakey response missing plaintext/ciphertext")
	}
	dek, err := base64.StdEncoding.DecodeString(dekB64)
	if err != nil {
		return Envelope{}, fmt.Errorf("envelope: decode DEK: %w", err)
	}

	// Encrypt with AES-256-GCM. The defer zeros the DEK; we KeepAlive(dek)
	// after the loop so the Go compiler doesn't elide the zeroing as
	// dead-store optimisation. See doc.go for the rationale.
	defer func() {
		zero(dek)
		runtime.KeepAlive(dek)
	}()

	block, err := aes.NewCipher(dek)
	if err != nil {
		return Envelope{}, fmt.Errorf("envelope: new AES cipher: %w", err)
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return Envelope{}, fmt.Errorf("envelope: new GCM: %w", err)
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return Envelope{}, fmt.Errorf("envelope: read nonce: %w", err)
	}
	ct := gcm.Seal(nil, nonce, plaintext, aad)

	return Envelope{
		Ciphertext: ct,
		WrappedDEK: wrapped,
		Nonce:      nonce,
		Algo:       "aes-256-gcm",
		KID:        kid,
		KeyVersion: parseKeyVersion(wrapped),
	}, nil
}

// Decrypt verifies that the row's kid matches the caller-supplied expected
// kid BEFORE calling OpenBao, then unwraps the DEK and AES-GCM-Opens the
// ciphertext. The kid check is the linchpin of layer 5 of the eight-layer
// tenant isolation invariant — bypassing it would let a row from Deployment
// A be decrypted under Deployment B's key (and silently succeed when the
// transit keys are wrapped identically).
//
// expectedKid is typically the deployment_id from the request context. It
// MUST be non-empty: an empty expectedKid means "I don't know whose data
// this is", which is never a valid decrypt scenario.
//
// aad must equal the aad supplied at encrypt time, byte-for-byte. Any
// mismatch surfaces as an AEAD authentication failure.
func (c *Client) Decrypt(ctx context.Context, env Envelope, expectedKid string, aad []byte) ([]byte, error) {
	if expectedKid == "" {
		return nil, ErrMissingExpectedKID
	}
	if env.KID == "" {
		return nil, ErrEmptyKID
	}
	// The critical check: BEFORE asking OpenBao to decrypt, refuse if the
	// row's kid disagrees with the caller's expected kid. If we let the
	// call through, the kid we pass in the URL path is the ROW's kid, and
	// OpenBao would happily decrypt with whichever key the policy allows —
	// which in a misconfigured system could be the wrong one.
	if env.KID != expectedKid {
		return nil, ErrKidMismatch
	}
	if err := validateKid(env.KID); err != nil {
		return nil, err
	}
	if env.WrappedDEK == "" {
		return nil, errors.New("envelope: wrapped DEK is empty")
	}

	sec, err := c.bao.Logical().WriteWithContext(ctx, "transit/decrypt/"+env.KID, map[string]any{
		"ciphertext": env.WrappedDEK,
	})
	if err != nil {
		return nil, fmt.Errorf("envelope: unwrap DEK: %w", err)
	}
	if sec == nil || sec.Data == nil {
		return nil, errors.New("envelope: decrypt response was empty")
	}
	dekB64, _ := sec.Data["plaintext"].(string)
	if dekB64 == "" {
		return nil, errors.New("envelope: decrypt response missing plaintext")
	}
	dek, err := base64.StdEncoding.DecodeString(dekB64)
	if err != nil {
		return nil, fmt.Errorf("envelope: decode DEK: %w", err)
	}
	defer func() {
		zero(dek)
		runtime.KeepAlive(dek)
	}()

	block, err := aes.NewCipher(dek)
	if err != nil {
		return nil, fmt.Errorf("envelope: new AES cipher: %w", err)
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("envelope: new GCM: %w", err)
	}
	if len(env.Nonce) != gcm.NonceSize() {
		return nil, fmt.Errorf("envelope: nonce length %d != %d", len(env.Nonce), gcm.NonceSize())
	}
	pt, err := gcm.Open(nil, env.Nonce, env.Ciphertext, aad)
	if err != nil {
		return nil, fmt.Errorf("envelope: AEAD open: %w", err)
	}
	return pt, nil
}

// RotateKey advances the transit key for kid to a new version. New writes
// will use the new version; old envelopes still decrypt because OpenBao
// retains every version until min_decryption_version is bumped.
func (c *Client) RotateKey(ctx context.Context, kid string) error {
	if err := validateKid(kid); err != nil {
		return err
	}
	if _, err := c.bao.Logical().WriteWithContext(ctx, "transit/keys/"+kid+"/rotate", nil); err != nil {
		return fmt.Errorf("envelope: rotate: %w", err)
	}
	return nil
}

// Rewrap re-wraps an existing WrappedDEK against the latest key version of
// kid. Returns the new wrapped DEK (and parsed key version) — caller is
// responsible for persisting it. No plaintext DEK ever leaves OpenBao.
func (c *Client) Rewrap(ctx context.Context, kid, wrappedDEK string) (string, int, error) {
	if err := validateKid(kid); err != nil {
		return "", 0, err
	}
	if wrappedDEK == "" {
		return "", 0, errors.New("envelope: wrappedDEK is empty")
	}
	sec, err := c.bao.Logical().WriteWithContext(ctx, "transit/rewrap/"+kid, map[string]any{
		"ciphertext": wrappedDEK,
	})
	if err != nil {
		return "", 0, fmt.Errorf("envelope: rewrap: %w", err)
	}
	if sec == nil || sec.Data == nil {
		return "", 0, errors.New("envelope: rewrap response was empty")
	}
	out, _ := sec.Data["ciphertext"].(string)
	if out == "" {
		return "", 0, errors.New("envelope: rewrap response missing ciphertext")
	}
	return out, parseKeyVersion(out), nil
}

// EnsureKey creates the transit key for kid if it does not already exist.
// Idempotent: if the key is present, the call is a no-op (OpenBao returns
// 200 with "already exists"-style data, which we don't inspect). Called by
// the provisioner when a new Deployment is created.
func (c *Client) EnsureKey(ctx context.Context, kid string) error {
	if err := validateKid(kid); err != nil {
		return err
	}
	_, err := c.bao.Logical().WriteWithContext(ctx, "transit/keys/"+kid, map[string]any{
		"type":                   "aes256-gcm96",
		"exportable":             false,
		"allow_plaintext_backup": false,
	})
	if err != nil {
		return fmt.Errorf("envelope: ensure key: %w", err)
	}
	return nil
}

// parseKeyVersion extracts N from a "vault:vN:<b64>" / "openbao:vN:<b64>"
// wrapped-DEK string. Returns 0 on any parse failure — callers should treat
// that as "unknown version" rather than crash.
func parseKeyVersion(wrap string) int {
	parts := strings.SplitN(wrap, ":", 3)
	if len(parts) < 3 {
		return 0
	}
	if !strings.HasPrefix(parts[1], "v") {
		return 0
	}
	n, err := strconv.Atoi(parts[1][1:])
	if err != nil {
		return 0
	}
	return n
}

// zero overwrites b with zero bytes. Use defer + runtime.KeepAlive to defeat
// the Go compiler's dead-store optimisation (see Encrypt/Decrypt).
func zero(b []byte) {
	for i := range b {
		b[i] = 0
	}
}

// Errors returned by the envelope package. Each constant matches one
// failure mode the caller can branch on.
var (
	// ErrEmptyKID is returned when Encrypt/Decrypt see an empty kid in the
	// row or arguments.
	ErrEmptyKID = errors.New("envelope: empty kid")
	// ErrMissingExpectedKID is returned by Decrypt when the caller did not
	// supply an expected kid. Defending against an accidental empty string
	// being treated as "match anything".
	ErrMissingExpectedKID = errors.New("envelope: missing expected kid (caller must source from request context)")
	// ErrKidMismatch is returned by Decrypt when the row's kid disagrees
	// with the caller-supplied expected kid. The OpenBao call is NOT made;
	// the persistence layer should translate this to a cross-tenant 403.
	ErrKidMismatch = errors.New("envelope: kid mismatch (cross-deployment access refused)")
)
