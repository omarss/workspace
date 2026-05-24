// Package cursor encodes and decodes the opaque pagination cursors used by
// list endpoints. The shape is base64url(json{"v":1,"k":"<created_at>","id":"<id>"}).
//
// ADR 011: the v field is mandatory; bumping it returns 410 Gone for old
// cursors rather than silently re-interpreting them.
package cursor

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"time"
)

// Cursor is the keyset for (created_at DESC, id DESC) pagination. Tenant-bound
// list queries combine the encoded created_at + id with their RLS-scoped
// SELECT.
type Cursor struct {
	V         int       `json:"v"`
	CreatedAt time.Time `json:"k"`
	ID        string    `json:"id"`
}

// CurrentVersion is the version stamp every newly-encoded cursor receives.
// Future migrations bump this and add a Decode-time mapping; old cursors that
// do not match are rejected with ErrVersionMismatch (HTTP 410 Gone).
const CurrentVersion = 1

// Sentinel errors. Handlers translate ErrVersionMismatch to 410 Gone and
// ErrBadCursor to 422 validation-failed.
var (
	ErrBadCursor       = errors.New("bad cursor")
	ErrVersionMismatch = errors.New("cursor version mismatch")
)

// Encode renders a Cursor as the opaque string returned in pagination.next_cursor.
// V is stamped to CurrentVersion automatically when the caller leaves it zero.
func Encode(c Cursor) string {
	if c.V == 0 {
		c.V = CurrentVersion
	}
	b, _ := json.Marshal(c)
	return base64.RawURLEncoding.EncodeToString(b)
}

// Decode parses a cursor returned to the server by a client. Mismatched
// versions return ErrVersionMismatch so the handler can return 410 Gone
// (clients must drop the stored cursor and re-paginate).
func Decode(s string) (Cursor, error) {
	raw, err := base64.RawURLEncoding.DecodeString(s)
	if err != nil {
		return Cursor{}, ErrBadCursor
	}
	var c Cursor
	if err := json.Unmarshal(raw, &c); err != nil {
		return Cursor{}, ErrBadCursor
	}
	if c.V != CurrentVersion {
		return Cursor{}, ErrVersionMismatch
	}
	if c.ID == "" {
		return Cursor{}, ErrBadCursor
	}
	return c, nil
}
