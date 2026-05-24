package pagination_test

import (
	"testing"

	"github.com/omarss/saas/internal/platform/pagination"
)

func TestClampLimit(t *testing.T) {
	cases := map[int]int{
		-1:  pagination.DefaultLimit,
		0:   pagination.DefaultLimit,
		1:   1,
		25:  25,
		200: 200,
		201: pagination.MaxLimit,
		999: pagination.MaxLimit,
	}
	for in, want := range cases {
		if got := pagination.ClampLimit(in); got != want {
			t.Errorf("ClampLimit(%d)=%d want %d", in, got, want)
		}
	}
}
