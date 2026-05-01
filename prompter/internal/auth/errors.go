package auth

import "errors"

// Domain errors for the auth flow. Handlers map these to HTTP status codes;
// the client sees a generic message for the verify-time errors so we don't
// leak which step failed.
var (
	ErrRateLimited       = errors.New("auth: rate limited")
	ErrInvalidChannel    = errors.New("auth: invalid channel")
	ErrInvalidIdentifier = errors.New("auth: invalid identifier")
	ErrChallengeNotFound = errors.New("auth: challenge not found")
	ErrChallengeExpired  = errors.New("auth: challenge expired")
	ErrChallengeConsumed = errors.New("auth: challenge already consumed")
	ErrTooManyAttempts   = errors.New("auth: too many attempts")
	ErrSessionNotFound   = errors.New("auth: session not found")
	ErrProvider          = errors.New("auth: provider error")
)
