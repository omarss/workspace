// Package whatsapp is a stdlib-only Twilio Messages API client for the
// WhatsApp channel. WhatsApp does not have native poll messages, so this
// adapter renders questions as plain text + a hint like "أجب بحرف A/B/C/D".
//
// Inbound is a Twilio webhook (Conversations or Messaging) — the HTTP
// server in `internal/server` mounts /webhooks/twilio/whatsapp and parses
// the form payload here.
package whatsapp

import (
	"context"
	"crypto/hmac"
	"crypto/sha1" //nolint:gosec // Twilio signature uses SHA1 by spec
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"
)

// Client posts WhatsApp messages via Twilio.
type Client struct {
	accountSID string
	authToken  string
	from       string // "whatsapp:+1...."
	httpClient *http.Client
}

// New constructs a client. h=nil falls back to a 10s default.
func New(accountSID, authToken, from string, h *http.Client) *Client {
	if h == nil {
		h = &http.Client{Timeout: 10 * time.Second}
	}
	return &Client{
		accountSID: accountSID,
		authToken:  authToken,
		from:       from,
		httpClient: h,
	}
}

// SendText posts a plain-text message to the given WhatsApp address.
// `to` must include the "whatsapp:" prefix Twilio expects.
func (c *Client) SendText(ctx context.Context, to, body string) error {
	form := url.Values{
		"From": {c.from},
		"To":   {to},
		"Body": {body},
	}
	endpoint := fmt.Sprintf("https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json", c.accountSID)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, strings.NewReader(form.Encode()))
	if err != nil {
		return fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.SetBasicAuth(c.accountSID, c.authToken)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("post: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 16<<10))
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return nil
	}
	return fmt.Errorf("twilio %d: %s", resp.StatusCode, string(raw))
}

// IncomingMessage is the parsed shape of a Twilio webhook POST.
type IncomingMessage struct {
	From string // "whatsapp:+966500000000"
	To   string
	Body string
	SID  string
}

// ParseWebhook reads the form body. Caller must call ValidateSignature
// before trusting any of the values.
func ParseWebhook(r *http.Request) (IncomingMessage, error) {
	if err := r.ParseForm(); err != nil {
		return IncomingMessage{}, fmt.Errorf("parse form: %w", err)
	}
	return IncomingMessage{
		From: r.PostForm.Get("From"),
		To:   r.PostForm.Get("To"),
		Body: r.PostForm.Get("Body"),
		SID:  r.PostForm.Get("MessageSid"),
	}, nil
}

// ValidateSignature checks the X-Twilio-Signature header against an
// HMAC-SHA1 of the URL + sorted form params, signed with authToken.
// See https://www.twilio.com/docs/usage/security#validating-requests.
//
// signedURL must be the publicly-visible URL Twilio called (host nginx
// rewrites can change this — pass the original).
func (c *Client) ValidateSignature(signedURL string, form url.Values, headerSig string) bool {
	if c.authToken == "" || headerSig == "" {
		return false
	}
	keys := make([]string, 0, len(form))
	for k := range form {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var b strings.Builder
	b.WriteString(signedURL)
	for _, k := range keys {
		for _, v := range form[k] {
			b.WriteString(k)
			b.WriteString(v)
		}
	}
	mac := hmac.New(sha1.New, []byte(c.authToken))
	mac.Write([]byte(b.String()))
	want := base64.StdEncoding.EncodeToString(mac.Sum(nil))
	return hmac.Equal([]byte(want), []byte(headerSig))
}
