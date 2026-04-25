// Package signing implements HMAC-SHA256 webhook signing in a Svix-compatible
// header format ("v1,<base64sig>"), with constant-time verification, replay
// protection via a timestamp tolerance window, and key rotation via
// space-separated signature lists.
//
// The signed payload is the canonical string:
//
//	{message_id}.{timestamp}.{body}
//
// where {timestamp} is decimal Unix epoch seconds. This matches Svix Server,
// so a tenant who already verifies Svix webhooks can reuse their existing
// receiver against ours.
package signing

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"strings"
	"time"
)

const scheme = "v1"

var (
	// ErrEmptySecret is returned when no signing secret is provided.
	ErrEmptySecret = errors.New("signing: empty secret")
	// ErrEmptyID is returned when no message id is provided.
	ErrEmptyID = errors.New("signing: empty message id")
	// ErrInvalidHeader is returned when the header carries no signature in a
	// scheme this version understands.
	ErrInvalidHeader = errors.New("signing: invalid header")
	// ErrTimestampSkew is returned when |now - ts| exceeds the tolerance.
	ErrTimestampSkew = errors.New("signing: timestamp outside tolerance")
	// ErrSignatureMismatch is returned when no candidate signature matched.
	ErrSignatureMismatch = errors.New("signing: signature mismatch")
)

// Sign produces a header value of the form "v1,<base64sig>" where the
// signature is HMAC-SHA256(secret, id.ts.body).
func Sign(secret []byte, id string, ts int64, body []byte) (string, error) {
	if len(secret) == 0 {
		return "", ErrEmptySecret
	}
	if id == "" {
		return "", ErrEmptyID
	}
	mac := hmac.New(sha256.New, secret)
	// Writing in pieces avoids materialising the joined payload.
	// hash.Hash never returns an error from Write (documented invariant).
	_, _ = fmt.Fprintf(mac, "%s.%d.", id, ts)
	_, _ = mac.Write(body)
	return scheme + "," + base64.StdEncoding.EncodeToString(mac.Sum(nil)), nil
}

// Verify checks header against the canonical signed string for (id, ts, body).
//
// The header may contain multiple space-separated entries to support key
// rotation; verification succeeds if any "v1,..." entry matches under the
// supplied secret.
//
// `now` and `tolerance` define the replay window: |now-ts| > tolerance is
// rejected with ErrTimestampSkew before any HMAC work is done.
func Verify(secret []byte, id string, ts int64, body []byte, header string, now time.Time, tolerance time.Duration) error {
	if len(secret) == 0 {
		return ErrEmptySecret
	}

	delta := now.Unix() - ts
	if delta < 0 {
		delta = -delta
	}
	if time.Duration(delta)*time.Second > tolerance {
		return ErrTimestampSkew
	}

	expectedHeader, err := Sign(secret, id, ts, body)
	if err != nil {
		return err
	}
	expectedRaw, err := base64.StdEncoding.DecodeString(expectedHeader[len(scheme)+1:])
	if err != nil {
		return err
	}

	sawValidScheme := false
	for _, entry := range strings.Fields(header) {
		name, payload, ok := strings.Cut(entry, ",")
		if !ok || name != scheme {
			continue
		}
		sawValidScheme = true
		gotRaw, err := base64.StdEncoding.DecodeString(payload)
		if err != nil {
			continue
		}
		if hmac.Equal(gotRaw, expectedRaw) {
			return nil
		}
	}
	if !sawValidScheme {
		return ErrInvalidHeader
	}
	return ErrSignatureMismatch
}
