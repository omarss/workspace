// Package etag formats and parses the platform's Weak ETag. Per AGENTS.md
// section 19, ETags use the format W/"v<row_seq>" where row_seq is a
// monotonic per-row sequence bumped by the bump_row_seq() trigger. PATCH /
// PUT / DELETE clients echo it via If-Match; mismatches return 412.
package etag

import (
	"errors"
	"strconv"
	"strings"
)

// ErrMalformed is returned by Parse when the input is not W/"v<int>".
var ErrMalformed = errors.New("malformed etag")

// Format renders a sequence number as the platform's weak ETag string.
func Format(seq int64) string {
	return `W/"v` + strconv.FormatInt(seq, 10) + `"`
}

// Parse extracts the numeric sequence from a weak ETag. Tolerates an absent
// W/ prefix because some HTTP clients strip it; the underlying sequence is
// the load-bearing piece.
func Parse(s string) (int64, error) {
	s = strings.TrimSpace(s)
	s = strings.TrimPrefix(s, "W/")
	if !strings.HasPrefix(s, `"v`) || !strings.HasSuffix(s, `"`) {
		return 0, ErrMalformed
	}
	body := strings.TrimSuffix(strings.TrimPrefix(s, `"v`), `"`)
	n, err := strconv.ParseInt(body, 10, 64)
	if err != nil {
		return 0, ErrMalformed
	}
	return n, nil
}
