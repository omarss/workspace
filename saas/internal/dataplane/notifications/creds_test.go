package notifications_test

import (
	"errors"
	"strings"
	"testing"

	"github.com/omarss/saas/internal/dataplane/notifications"
)

func TestValidateCredentialsForProvider_SMTPHappy(t *testing.T) {
	err := notifications.ValidateCredentialsForProvider(
		notifications.ProviderSMTP,
		notifications.CredentialsBundle{SMTP: &notifications.SMTPCredentials{Username: "u", Password: "p"}},
	)
	if err != nil {
		t.Fatalf("expected nil, got %v", err)
	}
}

func TestValidateCredentialsForProvider_SMTPMissingPassword(t *testing.T) {
	err := notifications.ValidateCredentialsForProvider(
		notifications.ProviderSMTP,
		notifications.CredentialsBundle{SMTP: &notifications.SMTPCredentials{Username: "u"}},
	)
	if !errors.Is(err, notifications.ErrInvalidCredentials) {
		t.Errorf("expected ErrInvalidCredentials, got %v", err)
	}
}

func TestValidateCredentialsForProvider_InAppRejectsExternalCreds(t *testing.T) {
	err := notifications.ValidateCredentialsForProvider(
		notifications.ProviderInApp,
		notifications.CredentialsBundle{SMTP: &notifications.SMTPCredentials{Username: "u", Password: "p"}},
	)
	if !errors.Is(err, notifications.ErrInvalidCredentials) {
		t.Errorf("expected ErrInvalidCredentials, got %v", err)
	}
}

func TestValidateCredentialsForProvider_SendGridHappy(t *testing.T) {
	err := notifications.ValidateCredentialsForProvider(
		notifications.ProviderSendGrid,
		notifications.CredentialsBundle{SendGrid: &notifications.SendGridCredentials{APIKey: "sg-key"}},
	)
	if err != nil {
		t.Fatalf("expected nil, got %v", err)
	}
}

func TestValidateCredentialsForProvider_SESHappy(t *testing.T) {
	err := notifications.ValidateCredentialsForProvider(
		notifications.ProviderSES,
		notifications.CredentialsBundle{SES: &notifications.SESCredentials{AccessKeyID: "AKIA", SecretAccessKey: "s"}},
	)
	if err != nil {
		t.Fatalf("expected nil, got %v", err)
	}
}

func TestValidateCredentialsForProvider_UnknownProvider(t *testing.T) {
	err := notifications.ValidateCredentialsForProvider(
		notifications.ChannelProvider("twilio"),
		notifications.CredentialsBundle{},
	)
	if !errors.Is(err, notifications.ErrInvalidProvider) {
		t.Errorf("expected ErrInvalidProvider, got %v", err)
	}
}

func TestMarshalCredentials_RoundTrip(t *testing.T) {
	in := notifications.CredentialsBundle{
		SendGrid: &notifications.SendGridCredentials{APIKey: "round-trip"},
	}
	s, err := notifications.MarshalCredentials(in)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if !strings.Contains(s, "round-trip") {
		t.Fatalf("payload missing key: %q", s)
	}
	out, err := notifications.UnmarshalCredentials(s)
	if err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if out.SendGrid == nil || out.SendGrid.APIKey != "round-trip" {
		t.Fatalf("round-trip mismatch: %+v", out)
	}
}

func TestMarshalCredentials_InAppReturnsEmpty(t *testing.T) {
	s, err := notifications.MarshalCredentials(notifications.CredentialsBundle{})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if s != "" {
		t.Errorf("expected empty payload for in-app channel, got %q", s)
	}
}
