package etag_test

import (
	"errors"
	"testing"

	"github.com/omarss/saas/internal/platform/etag"
)

func TestFormatParse_Roundtrip(t *testing.T) {
	for _, seq := range []int64{1, 17, 42, 1_000_000} {
		got, err := etag.Parse(etag.Format(seq))
		if err != nil {
			t.Fatalf("Parse(Format(%d)): %v", seq, err)
		}
		if got != seq {
			t.Fatalf("expected %d, got %d", seq, got)
		}
	}
}

func TestParse_TolerantNoWPrefix(t *testing.T) {
	got, err := etag.Parse(`"v7"`)
	if err != nil || got != 7 {
		t.Fatalf("expected 7, got %d, err=%v", got, err)
	}
}

func TestParse_Malformed(t *testing.T) {
	for _, s := range []string{"", "abc", `W/"7"`, `W/"vNaN"`} {
		if _, err := etag.Parse(s); !errors.Is(err, etag.ErrMalformed) {
			t.Errorf("expected ErrMalformed for %q, got %v", s, err)
		}
	}
}
