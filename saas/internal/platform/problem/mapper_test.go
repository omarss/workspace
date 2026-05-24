package problem_test

import (
	"errors"
	"testing"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/problem"
)

func TestFromError_Maps(t *testing.T) {
	cases := []struct {
		err        error
		wantType   string
		wantStatus int
	}{
		{auth.ErrUnauthorized, problem.TypeUnauthorized, 401},
		{auth.ErrCrossTenant, problem.TypeCrossTenant, 403},
		{auth.ErrMissingScope, problem.TypeForbidden, 403},
		{auth.ErrKeyRevoked, problem.TypeKeyRevoked, 401},
		{auth.ErrKeyExpired, problem.TypeKeyExpired, 401},
		{auth.ErrIPNotAllowed, problem.TypeIPNotAllowed, 403},
	}
	for _, c := range cases {
		p, ok := problem.FromError(c.err, "/v1/x")
		if !ok {
			t.Errorf("FromError(%v) ok=false", c.err)
			continue
		}
		if p.Type != c.wantType {
			t.Errorf("type=%q want %q", p.Type, c.wantType)
		}
		if p.Status != c.wantStatus {
			t.Errorf("status=%d want %d", p.Status, c.wantStatus)
		}
	}
}

func TestFromError_UnknownReturnsFalse(t *testing.T) {
	if _, ok := problem.FromError(errors.New("random"), "/x"); ok {
		t.Fatal("expected ok=false for unknown error")
	}
}
