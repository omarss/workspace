// Package resend implements notifier.EmailSender against the Resend HTTP
// API (https://resend.com/docs/api-reference/emails/send-email).
//
// We talk to it with stdlib net/http rather than pulling the resend-go SDK
// because the surface is tiny and a thin wrapper sidesteps the
// "no vendor SDK leaks" rule for the rest of the codebase.
package resend

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// DefaultEndpoint is overridden in tests via NewWithEndpoint.
const DefaultEndpoint = "https://api.resend.com"

// Client is safe for concurrent use.
type Client struct {
	apiKey   string
	from     string
	endpoint string
	http     *http.Client
}

// New returns a client using the production endpoint.
//
// `from` must be a verified sender on the Resend account, e.g.
// "qudrat <noreply@omarss.net>".
func New(apiKey, from string) *Client {
	return NewWithEndpoint(apiKey, from, DefaultEndpoint, nil)
}

// NewWithEndpoint is the test-friendly constructor. A nil http.Client falls
// back to a 10s-timeout default.
func NewWithEndpoint(apiKey, from, endpoint string, h *http.Client) *Client {
	if h == nil {
		h = &http.Client{Timeout: 10 * time.Second}
	}
	return &Client{apiKey: apiKey, from: from, endpoint: endpoint, http: h}
}

type sendRequest struct {
	From    string   `json:"from"`
	To      []string `json:"to"`
	Subject string   `json:"subject"`
	Text    string   `json:"text"`
}

type sendErrResponse struct {
	Name    string `json:"name"`
	Message string `json:"message"`
}

// SendOTP sends `code` to `to`. The body is plain text — adding HTML brings
// little value for a one-line message and makes deliverability auditing
// harder.
func (c *Client) SendOTP(ctx context.Context, to, code string) error {
	body := sendRequest{
		From:    c.from,
		To:      []string{to},
		Subject: "Your qudrat code",
		Text:    fmt.Sprintf("Your qudrat sign-in code is %s. It expires in 10 minutes.", code),
	}
	buf, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint+"/emails", bytes.NewReader(buf))
	if err != nil {
		return fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("post: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		// Drain so the keepalive connection can be reused.
		_, _ = io.Copy(io.Discard, resp.Body)
		return nil
	}

	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<10))
	var er sendErrResponse
	if json.Unmarshal(raw, &er) == nil && er.Message != "" {
		return fmt.Errorf("resend %d: %s", resp.StatusCode, er.Message)
	}
	return fmt.Errorf("resend %d: %s", resp.StatusCode, string(raw))
}
