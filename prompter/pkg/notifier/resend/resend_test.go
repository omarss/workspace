package resend

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestSendOTP_PostsExpectedPayload(t *testing.T) {
	t.Parallel()

	var captured struct {
		method string
		path   string
		auth   string
		ctype  string
		body   sendRequest
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		captured.method = r.Method
		captured.path = r.URL.Path
		captured.auth = r.Header.Get("Authorization")
		captured.ctype = r.Header.Get("Content-Type")
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &captured.body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"id":"deadbeef"}`))
	}))
	t.Cleanup(srv.Close)

	c := NewWithEndpoint("re_test_key", "prompter <noreply@example.com>", srv.URL, srv.Client())
	if err := c.SendOTP(context.Background(), "user@example.com", "123456"); err != nil {
		t.Fatalf("send: %v", err)
	}

	if captured.method != http.MethodPost {
		t.Errorf("method = %q, want POST", captured.method)
	}
	if captured.path != "/emails" {
		t.Errorf("path = %q, want /emails", captured.path)
	}
	if captured.auth != "Bearer re_test_key" {
		t.Errorf("auth = %q", captured.auth)
	}
	if captured.ctype != "application/json" {
		t.Errorf("content-type = %q", captured.ctype)
	}
	if captured.body.From != "prompter <noreply@example.com>" {
		t.Errorf("from = %q", captured.body.From)
	}
	if len(captured.body.To) != 1 || captured.body.To[0] != "user@example.com" {
		t.Errorf("to = %v", captured.body.To)
	}
	if !strings.Contains(captured.body.Text, "123456") {
		t.Errorf("text body missing code: %q", captured.body.Text)
	}
}

func TestSendOTP_SurfacesAPIError(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusUnprocessableEntity)
		_, _ = w.Write([]byte(`{"name":"validation_error","message":"invalid_to"}`))
	}))
	t.Cleanup(srv.Close)

	c := NewWithEndpoint("k", "f@example.com", srv.URL, srv.Client())
	err := c.SendOTP(context.Background(), "bad", "111111")
	if err == nil {
		t.Fatalf("expected error")
	}
	if !strings.Contains(err.Error(), "invalid_to") {
		t.Errorf("error should include API message; got %v", err)
	}
}
