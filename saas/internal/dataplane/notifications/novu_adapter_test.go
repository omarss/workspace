package notifications_test

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/omarss/saas/internal/dataplane/notifications"
)

// TestNovuRESTClient_TriggerWorkflow_HappyPath stands up a tiny test
// server matching Novu's POST /v1/events/trigger shape and asserts the
// adapter sends the right body + decodes the transactionId.
func TestNovuRESTClient_TriggerWorkflow_HappyPath(t *testing.T) {
	captured := struct {
		path        string
		auth        string
		contentType string
		body        map[string]any
	}{}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		captured.path = r.URL.Path
		captured.auth = r.Header.Get("Authorization")
		captured.contentType = r.Header.Get("Content-Type")
		b, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(b, &captured.body)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{"acknowledged":true,"status":"queued","transactionId":"tx_abc"}}`))
	}))
	defer srv.Close()

	cli, err := notifications.NewNovuRESTClient(notifications.NovuRESTOptions{
		BaseURL: srv.URL,
		APIKey:  "dev-key",
	})
	if err != nil {
		t.Fatalf("NewNovuRESTClient: %v", err)
	}
	txID, err := cli.TriggerWorkflow(context.Background(), "password-reset", "user_01H", map[string]any{"reset_url": "https://app/r"})
	if err != nil {
		t.Fatalf("TriggerWorkflow: %v", err)
	}
	if txID != "tx_abc" {
		t.Errorf("transactionId: got %q want tx_abc", txID)
	}
	if captured.path != "/v1/events/trigger" {
		t.Errorf("path: %q", captured.path)
	}
	if !strings.HasPrefix(captured.auth, "ApiKey ") {
		t.Errorf("auth header: %q", captured.auth)
	}
	if captured.contentType != "application/json" {
		t.Errorf("content-type: %q", captured.contentType)
	}
	if captured.body["name"] != "password-reset" {
		t.Errorf("body.name: %v", captured.body["name"])
	}
}

// TestNovuRESTClient_NonOK_SurfacesProviderUnavailable verifies that a
// non-2xx response from Novu is mapped to ErrProviderUnavailable. The
// outbox worker uses this to decide whether to retry.
func TestNovuRESTClient_NonOK_SurfacesProviderUnavailable(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(`{"error":"boom"}`))
	}))
	defer srv.Close()

	cli, _ := notifications.NewNovuRESTClient(notifications.NovuRESTOptions{
		BaseURL: srv.URL,
		APIKey:  "dev",
	})
	_, err := cli.TriggerWorkflow(context.Background(), "x", "user_01H", nil)
	if err == nil || !strings.Contains(err.Error(), "novu") {
		t.Fatalf("expected provider error, got %v", err)
	}
}

// TestNovuRESTClient_GetTransactionStatus_MapsStrings checks the
// Novu→platform status mapping.
func TestNovuRESTClient_GetTransactionStatus_MapsStrings(t *testing.T) {
	cases := map[string]notifications.NotificationStatus{
		"queued":    notifications.NotificationStatusQueued,
		"sent":      notifications.NotificationStatusSent,
		"completed": notifications.NotificationStatusDelivered,
		"delivered": notifications.NotificationStatusDelivered,
		"error":     notifications.NotificationStatusFailed,
		"failed":    notifications.NotificationStatusFailed,
		"unknown":   notifications.NotificationStatusQueued, // safe default
	}
	for novuStatus, want := range cases {
		t.Run(novuStatus, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(`{"data":{"_id":"n","transactionId":"tx_x","status":"` + novuStatus + `"}}`))
			}))
			defer srv.Close()
			cli, _ := notifications.NewNovuRESTClient(notifications.NovuRESTOptions{BaseURL: srv.URL, APIKey: "k"})
			got, err := cli.GetTransactionStatus(context.Background(), "tx_x")
			if err != nil {
				t.Fatalf("err: %v", err)
			}
			if got != want {
				t.Errorf("status %q: got %q want %q", novuStatus, got, want)
			}
		})
	}
}
