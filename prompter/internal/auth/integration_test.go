//go:build integration

// End-to-end auth flow against a real Postgres. Run with `make test-int`
// (which requires `make db-up migrate-up` first).
package auth_test

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"math/rand/v2"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"os"
	"sync"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/omarss/prompter/internal/auth"
	"github.com/omarss/prompter/internal/store"
	"github.com/omarss/prompter/pkg/notifier/devlog"
)

// captureEmail records the most recent code so the test can replay it.
type captureEmail struct {
	mu   sync.Mutex
	code string
}

func (c *captureEmail) SendOTP(_ context.Context, _, code string) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.code = code
	return nil
}

func (c *captureEmail) Code() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.code
}

type harness struct {
	srv    *httptest.Server
	client *http.Client
	email  *captureEmail
}

func newHarness(t *testing.T) *harness {
	t.Helper()
	dsn := os.Getenv("PROMPTER_TEST_DB_DSN")
	if dsn == "" {
		t.Skip("PROMPTER_TEST_DB_DSN not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatalf("pool: %v", err)
	}
	t.Cleanup(pool.Close)

	q := store.New(pool)
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	emailCap := &captureEmail{}
	smsFake := devlog.NewSMSVerifier(logger, "")

	otp := auth.NewOTPService(q, emailCap, smsFake, auth.OTPConfig{}, nil)
	sess := auth.NewSessionService(q, auth.SessionConfig{}, nil)

	h := auth.NewHandler(otp, sess, auth.CookieConfig{
		Name:     "prompter_session",
		Path:     "/",
		HTTPOnly: true,
		SameSite: http.SameSiteLaxMode,
	}, logger)

	r := chi.NewRouter()
	r.Route("/api", h.Mount)
	srv := httptest.NewServer(r)
	t.Cleanup(srv.Close)

	jar, _ := cookiejar.New(nil)
	return &harness{srv: srv, client: &http.Client{Jar: jar}, email: emailCap}
}

func (h *harness) post(t *testing.T, path string, body any) *http.Response {
	t.Helper()
	buf, err := json.Marshal(body)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	req, err := http.NewRequest(http.MethodPost, h.srv.URL+path, bytes.NewReader(buf))
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := h.client.Do(req)
	if err != nil {
		t.Fatalf("do: %v", err)
	}
	return resp
}

func (h *harness) get(t *testing.T, path string) *http.Response {
	t.Helper()
	resp, err := h.client.Get(h.srv.URL + path)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	return resp
}

func TestEmailOTP_FullFlow(t *testing.T) {
	h := newHarness(t)
	email := fmt.Sprintf("e2e+%s@example.com", uuid.NewString())

	// 1) start
	resp := h.post(t, "/api/auth/otp/start", map[string]string{
		"channel":    "email",
		"identifier": email,
	})
	if resp.StatusCode != http.StatusAccepted {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("start: %d %s", resp.StatusCode, string(body))
	}
	var startBody struct {
		ChallengeID uuid.UUID `json:"challenge_id"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&startBody); err != nil {
		t.Fatalf("decode start: %v", err)
	}
	_ = resp.Body.Close()

	code := h.email.Code()
	if code == "" {
		t.Fatalf("captureEmail received no code")
	}

	// 2) verify
	resp = h.post(t, "/api/auth/otp/verify", map[string]string{
		"challenge_id": startBody.ChallengeID.String(),
		"code":         code,
	})
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("verify: %d %s", resp.StatusCode, string(body))
	}
	_ = resp.Body.Close()

	// 3) /me with cookie
	resp = h.get(t, "/api/me")
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("/me after login: %d", resp.StatusCode)
	}
	var meBody struct {
		User struct {
			Email *string `json:"email"`
		} `json:"user"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&meBody); err != nil {
		t.Fatalf("decode me: %v", err)
	}
	_ = resp.Body.Close()
	if meBody.User.Email == nil || *meBody.User.Email != email {
		t.Fatalf("/me email mismatch: %v", meBody.User.Email)
	}

	// 4) logout
	resp = h.post(t, "/api/auth/logout", nil)
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("logout: %d", resp.StatusCode)
	}
	_ = resp.Body.Close()

	// 5) /me without active session
	resp = h.get(t, "/api/me")
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("/me after logout: %d, want 401", resp.StatusCode)
	}
	_ = resp.Body.Close()
}

func TestSMSOTP_FullFlow(t *testing.T) {
	h := newHarness(t)
	// Use a unique phone per run so the rate-limit slot is fresh. Saudi
	// mobile prefix +9665, then 9 random digits — fits E.164 (15 max).
	phone := fmt.Sprintf("+9665%09d", rand.Int64N(1_000_000_000))

	resp := h.post(t, "/api/auth/otp/start", map[string]string{
		"channel":    "sms",
		"identifier": phone,
	})
	if resp.StatusCode != http.StatusAccepted {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("start: %d %s", resp.StatusCode, string(body))
	}
	var startBody struct {
		ChallengeID uuid.UUID `json:"challenge_id"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&startBody)
	_ = resp.Body.Close()

	resp = h.post(t, "/api/auth/otp/verify", map[string]string{
		"challenge_id": startBody.ChallengeID.String(),
		"code":         devlog.DefaultSMSCode,
	})
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("verify: %d %s", resp.StatusCode, string(body))
	}
	_ = resp.Body.Close()

	resp = h.get(t, "/api/me")
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("/me: %d", resp.StatusCode)
	}
	_ = resp.Body.Close()
}

func TestVerify_BadCode_400(t *testing.T) {
	h := newHarness(t)
	email := fmt.Sprintf("bad+%s@example.com", uuid.NewString())

	resp := h.post(t, "/api/auth/otp/start", map[string]string{
		"channel":    "email",
		"identifier": email,
	})
	var startBody struct {
		ChallengeID uuid.UUID `json:"challenge_id"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&startBody)
	_ = resp.Body.Close()

	resp = h.post(t, "/api/auth/otp/verify", map[string]string{
		"challenge_id": startBody.ChallengeID.String(),
		"code":         "999999", // wrong
	})
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("verify bad: %d, want 400", resp.StatusCode)
	}
	_ = resp.Body.Close()
}

func TestStart_RejectsBadChannel(t *testing.T) {
	h := newHarness(t)
	resp := h.post(t, "/api/auth/otp/start", map[string]string{
		"channel":    "carrier-pigeon",
		"identifier": "anywhere",
	})
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("start bad channel: %d, want 400", resp.StatusCode)
	}
	_ = resp.Body.Close()
}

func TestStart_RateLimitsRapidRetry(t *testing.T) {
	h := newHarness(t)
	email := fmt.Sprintf("rl+%s@example.com", uuid.NewString())
	body := map[string]string{"channel": "email", "identifier": email}

	// Default rate limit is 3 per 5 minutes. The 4th must be 429.
	for i := 0; i < 3; i++ {
		resp := h.post(t, "/api/auth/otp/start", body)
		if resp.StatusCode != http.StatusAccepted {
			b, _ := io.ReadAll(resp.Body)
			t.Fatalf("attempt %d: %d %s", i+1, resp.StatusCode, string(b))
		}
		_ = resp.Body.Close()
	}
	resp := h.post(t, "/api/auth/otp/start", body)
	if resp.StatusCode != http.StatusTooManyRequests {
		t.Fatalf("4th attempt: %d, want 429", resp.StatusCode)
	}
	_ = resp.Body.Close()
}
