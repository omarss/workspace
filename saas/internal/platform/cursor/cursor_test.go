package cursor_test

import (
	"errors"
	"testing"
	"time"

	"github.com/omarss/saas/internal/platform/cursor"
)

func TestEncodeDecode_Roundtrip(t *testing.T) {
	now := time.Date(2026, 5, 24, 12, 0, 0, 0, time.UTC)
	encoded := cursor.Encode(cursor.Cursor{CreatedAt: now, ID: "tenant_X"})
	got, err := cursor.Decode(encoded)
	if err != nil {
		t.Fatalf("Decode: %v", err)
	}
	if !got.CreatedAt.Equal(now) || got.ID != "tenant_X" || got.V != cursor.CurrentVersion {
		t.Fatalf("roundtrip mismatch: %+v", got)
	}
}

func TestDecode_BadBase64(t *testing.T) {
	_, err := cursor.Decode("!!!not-base64!!!")
	if !errors.Is(err, cursor.ErrBadCursor) {
		t.Fatalf("expected ErrBadCursor, got %v", err)
	}
}

func TestDecode_VersionMismatchReturns410(t *testing.T) {
	// Manually construct a base64-encoded JSON with an unrecognised version
	// (Encode would auto-stamp the current one). ADR 011: decoder must
	// reject so the handler can return 410 Gone.
	encoded := "eyJ2Ijo5OTksImsiOiIyMDI2LTAxLTAxVDAwOjAwOjAwWiIsImlkIjoidGVuYW50X1gifQ"
	_, err := cursor.Decode(encoded)
	if !errors.Is(err, cursor.ErrVersionMismatch) {
		t.Fatalf("expected ErrVersionMismatch, got %v", err)
	}
}
