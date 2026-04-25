package server_test

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/omarss/ivr/internal/api/server"
)

func newTestHandler(t *testing.T) http.Handler {
	t.Helper()
	logger := slog.New(slog.NewJSONHandler(io.Discard, nil))
	h, err := server.New(server.Config{
		Logger:  logger,
		Version: "test",
	})
	if err != nil {
		t.Fatalf("server.New: %v", err)
	}
	return h
}

func TestHealthz_Ok(t *testing.T) {
	h := newTestHandler(t)
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/healthz", nil))

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rr.Code)
	}
	if got := rr.Header().Get("Content-Type"); !strings.HasPrefix(got, "application/json") {
		t.Errorf("content-type = %q", got)
	}
	var body map[string]string
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("body not json: %v", err)
	}
	if body["status"] != "ok" {
		t.Errorf("status field = %q", body["status"])
	}
	if body["version"] != "test" {
		t.Errorf("version field = %q", body["version"])
	}
}

func TestReadyz_Ok(t *testing.T) {
	h := newTestHandler(t)
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/readyz", nil))

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rr.Code)
	}
}

func TestUnknownRoute_404(t *testing.T) {
	h := newTestHandler(t)
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/does/not/exist", nil))
	if rr.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rr.Code)
	}
}

func TestHealthz_PostNotAllowed(t *testing.T) {
	h := newTestHandler(t)
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, httptest.NewRequest(http.MethodPost, "/healthz", nil))
	if rr.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want 405", rr.Code)
	}
}

func TestRequestID_HeaderEchoed(t *testing.T) {
	h := newTestHandler(t)
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	req.Header.Set("X-Request-Id", "test-rid-1")
	h.ServeHTTP(rr, req)

	if got := rr.Header().Get("X-Request-Id"); got != "test-rid-1" {
		t.Errorf("X-Request-Id = %q, want test-rid-1", got)
	}
}

func TestRequestID_Generated(t *testing.T) {
	h := newTestHandler(t)
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/healthz", nil))

	if got := rr.Header().Get("X-Request-Id"); got == "" {
		t.Error("X-Request-Id missing on response")
	}
}

func TestNew_RejectsNilLogger(t *testing.T) {
	_, err := server.New(server.Config{Logger: nil})
	if err == nil {
		t.Fatal("expected error for nil logger")
	}
}
