// Package devlog provides notifier implementations that emit OTP codes to a
// slog.Logger instead of a real provider. They exist so the full auth flow
// runs end-to-end on a developer laptop without any third-party credentials.
//
// NEVER wire these into a production binary — they leak codes to logs.
package devlog

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"log/slog"
)

// DefaultSMSCode is what SMSVerifier.Check accepts in dev. Override via
// NewSMSVerifier for tests that want a different fixture.
const DefaultSMSCode = "000000"

// EmailSender logs the code to slog at INFO. It always succeeds.
type EmailSender struct {
	logger *slog.Logger
}

// NewEmailSender returns a dev EmailSender that writes through l.
func NewEmailSender(l *slog.Logger) *EmailSender {
	return &EmailSender{logger: l}
}

// SendOTP logs the email/code pair at INFO level and returns nil.
func (e *EmailSender) SendOTP(_ context.Context, to, code string) error {
	e.logger.Info("dev email otp", "to", to, "code", code)
	return nil
}

// SMSVerifier returns a synthetic SID on Start and accepts a fixed code on
// Check. The fixed code can be overridden per instance for tests that need
// to assert the no-match path without flakiness.
type SMSVerifier struct {
	logger *slog.Logger
	code   string
}

// NewSMSVerifier returns a dev SMSVerifier. fixedCode is the only code
// Check will accept; an empty string falls back to DefaultSMSCode.
func NewSMSVerifier(l *slog.Logger, fixedCode string) *SMSVerifier {
	if fixedCode == "" {
		fixedCode = DefaultSMSCode
	}
	return &SMSVerifier{logger: l, code: fixedCode}
}

// Start logs the request and returns a synthetic verification SID.
func (s *SMSVerifier) Start(_ context.Context, phoneE164 string) (string, error) {
	var b [8]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	sid := "dev-" + hex.EncodeToString(b[:])
	s.logger.Info("dev sms start", "to", phoneE164, "sid", sid, "fixed_code", s.code)
	return sid, nil
}

// Check approves only the configured fixed code.
func (s *SMSVerifier) Check(_ context.Context, _, code string) (bool, error) {
	return code == s.code, nil
}
