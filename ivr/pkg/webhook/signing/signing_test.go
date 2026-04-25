package signing_test

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/omarss/ivr/pkg/webhook/signing"
)

const (
	testSecret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw" //nolint:gosec // test fixture, not a real credential
	testMsgID  = "msg_2KyfMUTUGzGB9ItfaUnVu5TGUEX"
)

// referenceSig is the canonical, dependency-free expected signature.
// We keep it independent of the package implementation so a refactor
// inside the package cannot make a buggy implementation pass.
func referenceSig(secret, id string, ts int64, body []byte) string {
	signed := fmt.Sprintf("%s.%d.%s", id, ts, body)
	mac := hmac.New(sha256.New, []byte(secret))
	_, _ = mac.Write([]byte(signed))
	return "v1," + base64.StdEncoding.EncodeToString(mac.Sum(nil))
}

func TestSign_Deterministic(t *testing.T) {
	body := []byte(`{"hello":"world"}`)
	ts := int64(1_712_345_678)

	got, err := signing.Sign([]byte(testSecret), testMsgID, ts, body)
	if err != nil {
		t.Fatalf("Sign: %v", err)
	}
	want := referenceSig(testSecret, testMsgID, ts, body)
	if got != want {
		t.Fatalf("signature drift\n got: %s\nwant: %s", got, want)
	}
	if !strings.HasPrefix(got, "v1,") {
		t.Fatalf("missing v1 scheme prefix: %s", got)
	}
}

func TestVerify_Roundtrip(t *testing.T) {
	body := []byte(`{"event":"call.completed"}`)
	ts := time.Now().Unix()

	sig, err := signing.Sign([]byte(testSecret), testMsgID, ts, body)
	if err != nil {
		t.Fatalf("Sign: %v", err)
	}
	if err := signing.Verify([]byte(testSecret), testMsgID, ts, body, sig, time.Now(), 5*time.Minute); err != nil {
		t.Fatalf("Verify: %v", err)
	}
}

func TestVerify_RejectsTamperedBody(t *testing.T) {
	body := []byte(`{"event":"call.completed"}`)
	ts := time.Now().Unix()
	sig, _ := signing.Sign([]byte(testSecret), testMsgID, ts, body)

	tampered := []byte(`{"event":"call.failed"}`)
	err := signing.Verify([]byte(testSecret), testMsgID, ts, tampered, sig, time.Now(), 5*time.Minute)
	if !errors.Is(err, signing.ErrSignatureMismatch) {
		t.Fatalf("expected ErrSignatureMismatch, got %v", err)
	}
}

func TestVerify_RejectsTamperedTimestamp(t *testing.T) {
	body := []byte(`{"event":"call.completed"}`)
	ts := time.Now().Unix()
	sig, _ := signing.Sign([]byte(testSecret), testMsgID, ts, body)

	err := signing.Verify([]byte(testSecret), testMsgID, ts+1, body, sig, time.Now(), 5*time.Minute)
	if !errors.Is(err, signing.ErrSignatureMismatch) {
		t.Fatalf("expected ErrSignatureMismatch, got %v", err)
	}
}

func TestVerify_RejectsTamperedID(t *testing.T) {
	body := []byte(`{"event":"call.completed"}`)
	ts := time.Now().Unix()
	sig, _ := signing.Sign([]byte(testSecret), testMsgID, ts, body)

	err := signing.Verify([]byte(testSecret), "msg_evil", ts, body, sig, time.Now(), 5*time.Minute)
	if !errors.Is(err, signing.ErrSignatureMismatch) {
		t.Fatalf("expected ErrSignatureMismatch, got %v", err)
	}
}

func TestVerify_RejectsWrongSecret(t *testing.T) {
	body := []byte(`{"event":"call.completed"}`)
	ts := time.Now().Unix()
	sig, _ := signing.Sign([]byte(testSecret), testMsgID, ts, body)

	err := signing.Verify([]byte("whsec_wrong"), testMsgID, ts, body, sig, time.Now(), 5*time.Minute)
	if !errors.Is(err, signing.ErrSignatureMismatch) {
		t.Fatalf("expected ErrSignatureMismatch, got %v", err)
	}
}

func TestVerify_RejectsExpiredTimestamp(t *testing.T) {
	body := []byte(`{"event":"call.completed"}`)
	ts := time.Now().Add(-10 * time.Minute).Unix()
	sig, _ := signing.Sign([]byte(testSecret), testMsgID, ts, body)

	err := signing.Verify([]byte(testSecret), testMsgID, ts, body, sig, time.Now(), 5*time.Minute)
	if !errors.Is(err, signing.ErrTimestampSkew) {
		t.Fatalf("expected ErrTimestampSkew, got %v", err)
	}
}

func TestVerify_RejectsFutureTimestamp(t *testing.T) {
	body := []byte(`{"event":"call.completed"}`)
	ts := time.Now().Add(10 * time.Minute).Unix()
	sig, _ := signing.Sign([]byte(testSecret), testMsgID, ts, body)

	err := signing.Verify([]byte(testSecret), testMsgID, ts, body, sig, time.Now(), 5*time.Minute)
	if !errors.Is(err, signing.ErrTimestampSkew) {
		t.Fatalf("expected ErrTimestampSkew, got %v", err)
	}
}

func TestVerify_RejectsMalformedHeader(t *testing.T) {
	cases := []string{
		"",
		"v2,abcd",
		"abcd",
		"v1,",
		",",
		"v1,not_base64!!!",
	}
	for _, h := range cases {
		err := signing.Verify([]byte(testSecret), testMsgID, time.Now().Unix(), []byte("{}"), h, time.Now(), 5*time.Minute)
		if !errors.Is(err, signing.ErrInvalidHeader) && !errors.Is(err, signing.ErrSignatureMismatch) {
			t.Fatalf("header %q: expected ErrInvalidHeader or ErrSignatureMismatch, got %v", h, err)
		}
	}
}

func TestVerify_AcceptsMultipleSigsForRotation(t *testing.T) {
	body := []byte(`{"event":"call.completed"}`)
	ts := time.Now().Unix()

	current, _ := signing.Sign([]byte("whsec_new"), testMsgID, ts, body)
	previous, _ := signing.Sign([]byte("whsec_old"), testMsgID, ts, body)

	combined := previous + " " + current

	if err := signing.Verify([]byte("whsec_new"), testMsgID, ts, body, combined, time.Now(), 5*time.Minute); err != nil {
		t.Fatalf("verify with rotation header (new key): %v", err)
	}
	if err := signing.Verify([]byte("whsec_old"), testMsgID, ts, body, combined, time.Now(), 5*time.Minute); err != nil {
		t.Fatalf("verify with rotation header (old key): %v", err)
	}
}

func TestSign_ErrorsOnEmptySecret(t *testing.T) {
	_, err := signing.Sign(nil, testMsgID, 1, []byte("{}"))
	if !errors.Is(err, signing.ErrEmptySecret) {
		t.Fatalf("expected ErrEmptySecret, got %v", err)
	}
}

func TestSign_ErrorsOnEmptyID(t *testing.T) {
	_, err := signing.Sign([]byte(testSecret), "", 1, []byte("{}"))
	if !errors.Is(err, signing.ErrEmptyID) {
		t.Fatalf("expected ErrEmptyID, got %v", err)
	}
}
