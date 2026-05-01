// Package twilio implements notifier.SMSVerifier against the Twilio Verify
// v2 API (https://www.twilio.com/docs/verify/api).
//
// We use stdlib net/http rather than the official twilio-go SDK because the
// Verify surface this app needs is two endpoints, the SDK pulls a large
// dependency tree, and the "no vendor SDK leaks" workspace rule keeps app
// code provider-agnostic.
package twilio

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// DefaultEndpoint is overridden in tests via NewVerifyClientWithEndpoint.
const DefaultEndpoint = "https://verify.twilio.com"

// VerifyClient is safe for concurrent use.
type VerifyClient struct {
	accountSID string
	authToken  string
	serviceSID string
	endpoint   string
	http       *http.Client
}

// NewVerifyClient returns a client against the production endpoint.
func NewVerifyClient(accountSID, authToken, serviceSID string) *VerifyClient {
	return NewVerifyClientWithEndpoint(accountSID, authToken, serviceSID, DefaultEndpoint, nil)
}

// NewVerifyClientWithEndpoint is the test-friendly constructor.
func NewVerifyClientWithEndpoint(accountSID, authToken, serviceSID, endpoint string, h *http.Client) *VerifyClient {
	if h == nil {
		h = &http.Client{Timeout: 10 * time.Second}
	}
	return &VerifyClient{
		accountSID: accountSID,
		authToken:  authToken,
		serviceSID: serviceSID,
		endpoint:   endpoint,
		http:       h,
	}
}

type verificationResp struct {
	SID    string `json:"sid"`
	Status string `json:"status"`
}

type apiError struct {
	Code     int    `json:"code"`
	Message  string `json:"message"`
	MoreInfo string `json:"more_info"`
}

// Start asks Verify to send a fresh code to phoneE164 over SMS. The
// returned SID is the Verification resource ID; we keep it for audit.
func (c *VerifyClient) Start(ctx context.Context, phoneE164 string) (string, error) {
	form := url.Values{
		"To":      {phoneE164},
		"Channel": {"sms"},
	}
	out, err := c.do(ctx, c.url("Verifications"), form)
	if err != nil {
		return "", err
	}
	if out.SID == "" {
		return "", fmt.Errorf("twilio: empty sid in response")
	}
	return out.SID, nil
}

// Check asks Verify whether `code` is the active verification for
// phoneE164. Twilio caps attempts internally; consecutive wrong codes
// expire the verification, after which Check returns approved=false until
// the caller starts a new one.
func (c *VerifyClient) Check(ctx context.Context, phoneE164, code string) (bool, error) {
	form := url.Values{
		"To":   {phoneE164},
		"Code": {code},
	}
	out, err := c.do(ctx, c.url("VerificationCheck"), form)
	if err != nil {
		// 404 here means "no active verification" — surface as denied,
		// not error. Other failures bubble up.
		var notFound notFoundError
		if errors.As(err, &notFound) {
			return false, nil
		}
		return false, err
	}
	return out.Status == "approved", nil
}

type notFoundError struct{ msg string }

func (e notFoundError) Error() string { return e.msg }

func (c *VerifyClient) url(endpoint string) string {
	return fmt.Sprintf("%s/v2/Services/%s/%s", c.endpoint, c.serviceSID, endpoint)
}

func (c *VerifyClient) do(ctx context.Context, target string, form url.Values) (verificationResp, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, target, strings.NewReader(form.Encode()))
	if err != nil {
		return verificationResp{}, fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.SetBasicAuth(c.accountSID, c.authToken)

	resp, err := c.http.Do(req)
	if err != nil {
		return verificationResp{}, fmt.Errorf("post: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 16<<10))
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		var out verificationResp
		if err := json.Unmarshal(raw, &out); err != nil {
			return verificationResp{}, fmt.Errorf("decode: %w", err)
		}
		return out, nil
	}

	var er apiError
	_ = json.Unmarshal(raw, &er)
	msg := er.Message
	if msg == "" {
		msg = string(raw)
	}
	if resp.StatusCode == http.StatusNotFound {
		return verificationResp{}, notFoundError{msg: fmt.Sprintf("twilio 404: %s", msg)}
	}
	return verificationResp{}, fmt.Errorf("twilio %d: %s", resp.StatusCode, msg)
}
