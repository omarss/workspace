package devlog

import (
	"context"
	"io"
	"log/slog"
	"strings"
	"testing"
)

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func TestEmailSender_AlwaysSucceeds(t *testing.T) {
	t.Parallel()
	s := NewEmailSender(discardLogger())
	if err := s.SendOTP(context.Background(), "user@example.com", "123456"); err != nil {
		t.Fatalf("send: %v", err)
	}
}

func TestSMSVerifier_StartReturnsSyntheticSID(t *testing.T) {
	t.Parallel()
	v := NewSMSVerifier(discardLogger(), "")
	sid, err := v.Start(context.Background(), "+966500000000")
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	if !strings.HasPrefix(sid, "dev-") {
		t.Fatalf("sid does not look synthetic: %q", sid)
	}
}

func TestSMSVerifier_CheckMatchesFixedCode(t *testing.T) {
	t.Parallel()
	v := NewSMSVerifier(discardLogger(), "777777")

	ok, err := v.Check(context.Background(), "+966500000000", "777777")
	if err != nil {
		t.Fatalf("check: %v", err)
	}
	if !ok {
		t.Fatalf("expected approved for matching fixed code")
	}

	ok, err = v.Check(context.Background(), "+966500000000", "999999")
	if err != nil {
		t.Fatalf("check: %v", err)
	}
	if ok {
		t.Fatalf("expected denied for mismatched code")
	}
}

func TestSMSVerifier_DefaultCodeApplied(t *testing.T) {
	t.Parallel()
	v := NewSMSVerifier(discardLogger(), "")
	ok, err := v.Check(context.Background(), "+966500000000", DefaultSMSCode)
	if err != nil {
		t.Fatalf("check: %v", err)
	}
	if !ok {
		t.Fatalf("default code must be accepted when none is set")
	}
}
