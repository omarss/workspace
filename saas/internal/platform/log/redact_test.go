package log_test

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"strings"
	"testing"

	platformlog "github.com/omarss/saas/internal/platform/log"
)

func TestIsRedactedKey_Static(t *testing.T) {
	for _, k := range []string{"authorization", "Authorization", "AUTHORIZATION", "password", "api_key", "vault_token", "wrapped_dek"} {
		if !platformlog.IsRedactedKey(k) {
			t.Errorf("expected %q redacted", k)
		}
	}
	for _, k := range []string{"name", "slug", "tenant_id"} {
		if platformlog.IsRedactedKey(k) {
			t.Errorf("expected %q not redacted", k)
		}
	}
}

func TestRegisterRedactedKey_Dynamic(t *testing.T) {
	platformlog.RegisterRedactedKey("payment_card_pan")
	if !platformlog.IsRedactedKey("Payment_Card_PAN") {
		t.Fatal("dynamic registration did not stick (case-insensitive)")
	}
}

func TestHandler_RedactsStaticKey(t *testing.T) {
	var buf bytes.Buffer
	logger := platformlog.New(platformlog.Options{Output: &buf})
	logger.Info("login", "password", "hunter2", "tenant_id", "tenant_X")
	got := buf.String()
	if !strings.Contains(got, `"password":"[REDACTED]"`) {
		t.Errorf("expected password redacted, got %s", got)
	}
	if !strings.Contains(got, `"tenant_id":"tenant_X"`) {
		t.Errorf("expected tenant_id intact, got %s", got)
	}
}

type paymentRecord struct {
	UserID string `json:"user_id"`
	CardNo string `json:"card_no" pii:"true"`
	Note   string `json:"note"`
}

func TestHandler_ScrubStructByTag(t *testing.T) {
	var buf bytes.Buffer
	logger := platformlog.New(platformlog.Options{Output: &buf})
	logger.Info("charge", "record", paymentRecord{
		UserID: "user_X",
		CardNo: "4242 4242 4242 4242",
		Note:   "ok",
	})
	// Parse the JSON line to assert the scrubbed structure.
	var line map[string]any
	if err := json.Unmarshal(buf.Bytes()[:buf.Len()-1], &line); err != nil {
		t.Fatalf("invalid json: %v\n%s", err, buf.String())
	}
	rec, ok := line["record"].(map[string]any)
	if !ok {
		t.Fatalf("record not an object: %v", line["record"])
	}
	if rec["card_no"] != "[REDACTED]" {
		t.Errorf("card_no not redacted: %v", rec["card_no"])
	}
	if rec["user_id"] != "user_X" {
		t.Errorf("user_id mangled: %v", rec["user_id"])
	}
}

func TestHandler_StaticKeyTakesPrecedence(t *testing.T) {
	var buf bytes.Buffer
	logger := platformlog.New(platformlog.Options{Output: &buf, Level: slog.LevelInfo})
	logger.Info("vault op", "vault_token", "s.AAAA")
	if !strings.Contains(buf.String(), `"vault_token":"[REDACTED]"`) {
		t.Errorf("expected vault_token redacted: %s", buf.String())
	}
}
