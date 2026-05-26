// Phase 13 — IP allowlist middleware tests. Covers the §17.3 matrix:
//   - non-operator pass-through (no enforcement)
//   - operator with empty allowlist passes
//   - operator with allowlist {10.0.0.0/24}, request from 10.0.0.5 -> 200
//   - operator with allowlist {10.0.0.0/24}, request from 192.168.1.1 -> 403
//   - operator with mixed v4/v6 allowlist honors both
//   - lookup error -> 401 (no leak of repo failure)

package operatorjwt_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/auth/operatorjwt"
)

type fakeLookup struct {
	allowlist map[string][]string
	err       error
}

func (f *fakeLookup) GetOperatorIPAllowlist(_ context.Context, opID string) ([]string, error) {
	if f.err != nil {
		return nil, f.err
	}
	return f.allowlist[opID], nil
}

// runIPAllow drives the middleware with no trusted-proxy CIDRs. The
// trusted-proxy paths are exercised separately by
// TestIPAllowlistTrustedProxyHonorsXRealIP /
// TestIPAllowlistXRealIPIgnoredFromUntrustedSource which set up the
// request manually so the helper can stay narrow.
func runIPAllow(t *testing.T, p auth.Principal, remoteAddr string, lookup operatorjwt.OperatorLookup) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest(http.MethodGet, "/control/v1/deployments", nil)
	r.RemoteAddr = remoteAddr
	if p.ActorType != "" || p.ActorID != "" {
		r = r.WithContext(auth.WithPrincipal(r.Context(), p))
	}
	w := httptest.NewRecorder()
	h := operatorjwt.IPAllowlistMiddleware(lookup, operatorjwt.IPAllowlistOptions{})(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	h.ServeHTTP(w, r)
	return w
}

func TestIPAllowlistNonOperatorPassesThrough(t *testing.T) {
	w := runIPAllow(t,
		auth.Principal{ActorType: auth.ActorUser, ActorID: "user_x"},
		"203.0.113.5:5000",
		&fakeLookup{},
	)
	if w.Code != http.StatusOK {
		t.Errorf("status=%d want 200", w.Code)
	}
}

func TestIPAllowlistEmptyListAllowsAny(t *testing.T) {
	w := runIPAllow(t,
		auth.Principal{ActorType: auth.ActorOperator, ActorID: "op_x"},
		"203.0.113.5:5000",
		&fakeLookup{allowlist: map[string][]string{"op_x": nil}},
	)
	if w.Code != http.StatusOK {
		t.Errorf("status=%d want 200", w.Code)
	}
}

func TestIPAllowlistInsideCIDRAllowed(t *testing.T) {
	w := runIPAllow(t,
		auth.Principal{ActorType: auth.ActorOperator, ActorID: "op_x"},
		"10.0.0.5:5000",
		&fakeLookup{allowlist: map[string][]string{"op_x": {"10.0.0.0/24"}}},
	)
	if w.Code != http.StatusOK {
		t.Errorf("status=%d want 200; body=%s", w.Code, w.Body.String())
	}
}

func TestIPAllowlistOutsideCIDRRefused(t *testing.T) {
	w := runIPAllow(t,
		auth.Principal{ActorType: auth.ActorOperator, ActorID: "op_x"},
		"192.168.1.1:5000",
		&fakeLookup{allowlist: map[string][]string{"op_x": {"10.0.0.0/24"}}},
	)
	if w.Code != http.StatusForbidden {
		t.Errorf("status=%d want 403", w.Code)
	}
	if !strings.Contains(w.Body.String(), "ip-not-allowlisted") {
		t.Errorf("expected ip-not-allowlisted in body, got %s", w.Body.String())
	}
}

func TestIPAllowlistMixedV4V6Honored(t *testing.T) {
	cases := []struct {
		name   string
		remote string
		want   int
	}{
		{"v4 in v4 cidr", "10.0.0.5:5000", http.StatusOK},
		{"v6 in v6 cidr", "[2001:db8::1]:5000", http.StatusOK},
		{"v4 out", "203.0.113.5:5000", http.StatusForbidden},
		{"v6 out", "[2001:dc8::1]:5000", http.StatusForbidden},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			w := runIPAllow(t,
				auth.Principal{ActorType: auth.ActorOperator, ActorID: "op_x"},
				c.remote,
				&fakeLookup{allowlist: map[string][]string{"op_x": {"10.0.0.0/24", "2001:db8::/32"}}},
			)
			if w.Code != c.want {
				t.Errorf("status=%d want %d (body=%s)", w.Code, c.want, w.Body.String())
			}
		})
	}
}

func TestIPAllowlistLookupErrorReturns401(t *testing.T) {
	w := runIPAllow(t,
		auth.Principal{ActorType: auth.ActorOperator, ActorID: "op_x"},
		"10.0.0.5:5000",
		&fakeLookup{err: errors.New("boom")},
	)
	if w.Code != http.StatusUnauthorized {
		t.Errorf("status=%d want 401", w.Code)
	}
}

func TestIPAllowlistTrustedProxyHonorsXRealIP(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/control/v1/deployments", nil)
	r.RemoteAddr = "127.0.0.1:5000" // request from the trusted proxy
	r.Header.Set("X-Real-IP", "10.0.0.5")
	r = r.WithContext(auth.WithPrincipal(r.Context(), auth.Principal{
		ActorType: auth.ActorOperator, ActorID: "op_x",
	}))
	w := httptest.NewRecorder()
	lookup := &fakeLookup{allowlist: map[string][]string{"op_x": {"10.0.0.0/24"}}}
	opts := operatorjwt.IPAllowlistOptions{TrustedProxies: []string{"127.0.0.0/8"}}
	h := operatorjwt.IPAllowlistMiddleware(lookup, opts)(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	h.ServeHTTP(w, r)
	if w.Code != http.StatusOK {
		t.Errorf("status=%d want 200 (X-Real-IP should be honored from trusted proxy); body=%s",
			w.Code, w.Body.String())
	}
}

func TestIPAllowlistXRealIPIgnoredFromUntrustedSource(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/control/v1/deployments", nil)
	r.RemoteAddr = "203.0.113.99:5000" // untrusted edge
	r.Header.Set("X-Real-IP", "10.0.0.5")
	r = r.WithContext(auth.WithPrincipal(r.Context(), auth.Principal{
		ActorType: auth.ActorOperator, ActorID: "op_x",
	}))
	w := httptest.NewRecorder()
	lookup := &fakeLookup{allowlist: map[string][]string{"op_x": {"10.0.0.0/24"}}}
	// Empty TrustedProxies -> the X-Real-IP must be ignored.
	opts := operatorjwt.IPAllowlistOptions{}
	h := operatorjwt.IPAllowlistMiddleware(lookup, opts)(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	h.ServeHTTP(w, r)
	if w.Code != http.StatusForbidden {
		t.Errorf("status=%d want 403 (untrusted X-Real-IP must be ignored); body=%s",
			w.Code, w.Body.String())
	}
}
