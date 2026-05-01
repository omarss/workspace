package twilio

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestStart_PostsForm(t *testing.T) {
	t.Parallel()
	var captured struct {
		path  string
		auth  string
		to    string
		ch    string
		ctype string
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		captured.path = r.URL.Path
		captured.auth = r.Header.Get("Authorization")
		captured.ctype = r.Header.Get("Content-Type")
		_ = r.ParseForm()
		captured.to = r.PostForm.Get("To")
		captured.ch = r.PostForm.Get("Channel")
		_, _ = w.Write([]byte(`{"sid":"VEabc123","status":"pending"}`))
	}))
	t.Cleanup(srv.Close)

	c := NewVerifyClientWithEndpoint("AC1", "secret", "VAxyz", srv.URL, srv.Client())
	sid, err := c.Start(context.Background(), "+966500000000")
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	if sid != "VEabc123" {
		t.Errorf("sid = %q, want VEabc123", sid)
	}
	if captured.path != "/v2/Services/VAxyz/Verifications" {
		t.Errorf("path = %q", captured.path)
	}
	if !strings.HasPrefix(captured.auth, "Basic ") {
		t.Errorf("auth not basic: %q", captured.auth)
	}
	if captured.ctype != "application/x-www-form-urlencoded" {
		t.Errorf("content-type = %q", captured.ctype)
	}
	if captured.to != "+966500000000" {
		t.Errorf("to = %q", captured.to)
	}
	if captured.ch != "sms" {
		t.Errorf("channel = %q", captured.ch)
	}
}

func TestCheck_ApprovedAndDenied(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = r.ParseForm()
		switch r.PostForm.Get("Code") {
		case "111111":
			_, _ = w.Write([]byte(`{"status":"approved"}`))
		default:
			_, _ = w.Write([]byte(`{"status":"pending"}`))
		}
	}))
	t.Cleanup(srv.Close)

	c := NewVerifyClientWithEndpoint("AC1", "secret", "VAxyz", srv.URL, srv.Client())

	ok, err := c.Check(context.Background(), "+966500000000", "111111")
	if err != nil {
		t.Fatalf("check approved: %v", err)
	}
	if !ok {
		t.Fatalf("approved code rejected")
	}

	ok, err = c.Check(context.Background(), "+966500000000", "222222")
	if err != nil {
		t.Fatalf("check denied: %v", err)
	}
	if ok {
		t.Fatalf("non-approved code returned ok")
	}
}

// 404 means "no active verification for that number" — should surface as
// denied, not an error, so the user gets a clean "wrong code" UX.
func TestCheck_404IsDenied(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"code":20404,"message":"not found"}`))
	}))
	t.Cleanup(srv.Close)

	c := NewVerifyClientWithEndpoint("AC1", "secret", "VAxyz", srv.URL, srv.Client())
	ok, err := c.Check(context.Background(), "+966500000000", "111111")
	if err != nil {
		t.Fatalf("err = %v, want nil", err)
	}
	if ok {
		t.Fatalf("404 must surface as denied")
	}
}

func TestStart_SurfacesError(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"code":60200,"message":"Invalid parameter"}`))
	}))
	t.Cleanup(srv.Close)

	c := NewVerifyClientWithEndpoint("AC1", "secret", "VAxyz", srv.URL, srv.Client())
	_, err := c.Start(context.Background(), "+966500000000")
	if err == nil {
		t.Fatalf("expected error")
	}
	if !strings.Contains(err.Error(), "Invalid parameter") {
		t.Errorf("err should include API message; got %v", err)
	}
}
