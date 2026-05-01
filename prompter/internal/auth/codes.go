// Package auth implements the email/SMS OTP login flow and session
// management for the prompter API.
//
// codes.go covers the email-path primitives: a 6-digit OTP drawn from
// crypto/rand, a bcrypt hash for at-rest storage, and a comparison helper
// used during /verify. The SMS path delegates secret handling to Twilio
// Verify and so does not use these helpers.
package auth

import (
	"crypto/rand"
	"errors"
	"fmt"
	"math/big"

	"golang.org/x/crypto/bcrypt"
)

// otpDigits keeps every code six digits — long enough that 1-in-10^6 luck
// won't break the attempt cap, short enough to type without typos.
const otpDigits = 6

// otpModulus = 10^otpDigits, the upper bound (exclusive) for crypto/rand.
var otpModulus = func() *big.Int {
	m := big.NewInt(1)
	ten := big.NewInt(10)
	for range otpDigits {
		m.Mul(m, ten)
	}
	return m
}()

// GenerateOTP returns a zero-padded six-digit code drawn from crypto/rand.
// Bias from `rand.Int` over a power-of-ten range is negligible.
func GenerateOTP() (string, error) {
	n, err := rand.Int(rand.Reader, otpModulus)
	if err != nil {
		return "", fmt.Errorf("rand.Int: %w", err)
	}
	return fmt.Sprintf("%0*d", otpDigits, n.Int64()), nil
}

// HashOTP returns a bcrypt hash of the code. Cost stays at the library
// default — high enough to slow brute force if the DB is ever dumped, low
// enough that /verify stays sub-200ms.
func HashOTP(code string) (string, error) {
	h, err := bcrypt.GenerateFromPassword([]byte(code), bcrypt.DefaultCost)
	if err != nil {
		return "", fmt.Errorf("bcrypt: %w", err)
	}
	return string(h), nil
}

// ErrOTPMismatch is returned by VerifyOTP when the supplied code does not
// match the stored hash. Callers should not surface anything more specific
// to clients (avoids enumeration about which path failed).
var ErrOTPMismatch = errors.New("auth: otp mismatch")

// VerifyOTP returns nil iff the bcrypt hash matches the code, ErrOTPMismatch
// on a clean failure, or a wrapped error on internal trouble (e.g. malformed
// stored hash).
func VerifyOTP(hash, code string) error {
	err := bcrypt.CompareHashAndPassword([]byte(hash), []byte(code))
	switch {
	case err == nil:
		return nil
	case errors.Is(err, bcrypt.ErrMismatchedHashAndPassword):
		return ErrOTPMismatch
	default:
		return fmt.Errorf("bcrypt compare: %w", err)
	}
}
