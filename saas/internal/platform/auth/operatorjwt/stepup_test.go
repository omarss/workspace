// Phase 13 — step-up middleware tests. Covers the §17.3 matrix rows:
//   - missing principal -> 401
//   - non-operator principal -> 403 (no step-up retry)
//   - operator without AMR -> 403 + step-up-required
//   - operator without acr=gold -> 403 + step-up-required
//   - operator with auth_time > 5min -> 403 + step-up-required
//   - operator fresh + gold + strong AMR -> 200

package operatorjwt_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/auth/operatorjwt"
)

const okBody = "ok"

func okHandler(t *testing.T) http.Handler {
	t.Helper()
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(okBody))
	})
}

func mwWithClock(t *testing.T, p auth.Principal, now time.Time) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest(http.MethodPost, "/control/v1/deployments/dep_x/purge", nil)
	if p.ActorType != "" || p.ActorID != "" {
		r = r.WithContext(auth.WithPrincipal(r.Context(), p))
	}
	w := httptest.NewRecorder()
	h := operatorjwt.RequireStepUp(func() time.Time { return now })(okHandler(t))
	h.ServeHTTP(w, r)
	return w
}

func TestStepUpMissingPrincipalReturns401(t *testing.T) {
	w := mwWithClock(t, auth.Principal{}, time.Now())
	if w.Code != http.StatusUnauthorized {
		t.Errorf("status=%d want 401", w.Code)
	}
}

func TestStepUpNonOperatorReturns403WithoutStepUpHint(t *testing.T) {
	p := auth.Principal{ActorType: auth.ActorUser, ActorID: "user_x"}
	w := mwWithClock(t, p, time.Now())
	if w.Code != http.StatusForbidden {
		t.Errorf("status=%d want 403", w.Code)
	}
	if strings.Contains(w.Body.String(), "step-up-required") {
		t.Errorf("non-operator should not get step-up retry hint: %s", w.Body.String())
	}
}

func TestStepUpNoStrongAMRReturnsStepUpRequired(t *testing.T) {
	p := auth.Principal{
		ActorType: auth.ActorOperator,
		ActorID:   "op_x",
		AMR:       []string{"pwd"}, // password only, no MFA
		ACR:       "gold",
		AuthTime:  time.Now(),
	}
	w := mwWithClock(t, p, time.Now())
	if w.Code != http.StatusForbidden {
		t.Errorf("status=%d want 403", w.Code)
	}
	assertProblemType(t, w, "step-up-required")
}

func TestStepUpNonGoldACRReturnsStepUpRequired(t *testing.T) {
	p := auth.Principal{
		ActorType: auth.ActorOperator,
		ActorID:   "op_x",
		AMR:       []string{"pwd", "otp"},
		ACR:       "silver",
		AuthTime:  time.Now(),
	}
	w := mwWithClock(t, p, time.Now())
	if w.Code != http.StatusForbidden {
		t.Errorf("status=%d want 403", w.Code)
	}
	assertProblemType(t, w, "step-up-required")
}

func TestStepUpExpiredAuthTimeReturnsStepUpRequired(t *testing.T) {
	authTime := time.Now().Add(-10 * time.Minute) // 10 min ago, beyond 5-min window
	p := auth.Principal{
		ActorType: auth.ActorOperator,
		ActorID:   "op_x",
		AMR:       []string{"pwd", "otp"},
		ACR:       "gold",
		AuthTime:  authTime,
	}
	w := mwWithClock(t, p, time.Now())
	if w.Code != http.StatusForbidden {
		t.Errorf("status=%d want 403", w.Code)
	}
	assertProblemType(t, w, "step-up-required")
}

func TestStepUpZeroAuthTimeReturnsStepUpRequired(t *testing.T) {
	p := auth.Principal{
		ActorType: auth.ActorOperator,
		ActorID:   "op_x",
		AMR:       []string{"pwd", "otp"},
		ACR:       "gold",
		// AuthTime explicitly zero -> token had no auth_time claim
	}
	w := mwWithClock(t, p, time.Now())
	if w.Code != http.StatusForbidden {
		t.Errorf("status=%d want 403", w.Code)
	}
	assertProblemType(t, w, "step-up-required")
}

func TestStepUpFreshOperatorWithStrongAMRSucceeds(t *testing.T) {
	now := time.Now()
	p := auth.Principal{
		ActorType: auth.ActorOperator,
		ActorID:   "op_x",
		AMR:       []string{"pwd", "otp"},
		ACR:       "gold",
		AuthTime:  now.Add(-1 * time.Minute), // 1 min ago, within window
	}
	w := mwWithClock(t, p, now)
	if w.Code != http.StatusOK {
		t.Errorf("status=%d want 200; body=%s", w.Code, w.Body.String())
	}
	if w.Body.String() != okBody {
		t.Errorf("body=%q want %q", w.Body.String(), okBody)
	}
}

func TestStepUpWebauthnAMRAcceptedAsStrong(t *testing.T) {
	now := time.Now()
	p := auth.Principal{
		ActorType: auth.ActorOperator,
		ActorID:   "op_x",
		AMR:       []string{"pwd", "hwk"}, // hardware key — phishing-resistant
		ACR:       "gold",
		AuthTime:  now,
	}
	w := mwWithClock(t, p, now)
	if w.Code != http.StatusOK {
		t.Errorf("status=%d want 200", w.Code)
	}
}

// assertProblemType decodes the response body as RFC 9457 problem-details
// and asserts the URI ends with "/<slug>". Currently every step-up
// branch returns the same slug ("step-up-required"); the parameter
// is retained so additional middleware-level problems can reuse the
// helper without a new signature when the §17.3 matrix grows.
//
//nolint:unparam // slug is intentionally parametric for matrix growth
func assertProblemType(t *testing.T, w *httptest.ResponseRecorder, slug string) {
	t.Helper()
	var p struct {
		Type   string `json:"type"`
		Status int    `json:"status"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &p); err != nil {
		t.Fatalf("decode problem: %v; body=%s", err, w.Body.String())
	}
	if !strings.HasSuffix(p.Type, "/"+slug) {
		t.Errorf("problem type=%q does not end with /%s", p.Type, slug)
	}
}
