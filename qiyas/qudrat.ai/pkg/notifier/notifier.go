// Package notifier defines the wire-level contracts the auth flow needs to
// deliver one-time codes. Implementations live in subpackages
// (pkg/notifier/devlog for dev, pkg/notifier/resend for email,
// pkg/notifier/twilio for SMS) and are selected at process start.
//
// The two channels intentionally have different shapes:
//
//   - EmailSender takes a plaintext code we generated locally; we keep the
//     bcrypt hash and verify in-process.
//   - SMSVerifier delegates code generation, delivery, retries, and check
//     to the provider. We store only the verification SID.
//
// Keeping these separate lets each adapter be a thin pass-through to its
// vendor instead of pretending the channels are symmetric.
package notifier

import "context"

// EmailSender delivers a one-time code to an email address. It does not
// generate the code — auth.GenerateOTP owns that.
type EmailSender interface {
	SendOTP(ctx context.Context, to, code string) error
}

// SMSVerifier wraps a provider that generates, delivers, and verifies SMS
// codes itself (Twilio Verify and friends).
type SMSVerifier interface {
	// Start asks the provider to send a fresh code to phoneE164 and returns
	// the verification SID for audit/logging.
	Start(ctx context.Context, phoneE164 string) (verificationSID string, err error)
	// Check asks the provider whether code is valid for phoneE164 right now.
	// Approval is binary; the provider tracks attempts and TTL internally.
	Check(ctx context.Context, phoneE164, code string) (approved bool, err error)
}
