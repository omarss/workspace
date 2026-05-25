package notifications

import (
	"bytes"
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

// NovuRESTClient is the handwritten REST client for Novu v3.15. Novu only
// ships a TypeScript SDK; we hand-roll the small subset of v1 endpoints the
// platform consumes:
//
//	POST /v1/events/trigger           — trigger a workflow for a subscriber
//	GET  /v1/notifications/{id}        — read transaction status (mapped)
//	PUT  /v1/integrations/{id}         — push BYOK creds into a Novu integration
//	POST /v1/integrations              — create when integration id is unknown
//	POST /v1/subscribers               — create/upsert a subscriber
//
// All URL shapes were verified against https://docs.novu.co/api-reference
// at Phase 6 pin time (v3.15.0). The struct exposes Options so tests can
// substitute a *httptest.Server.
type NovuRESTClient struct {
	baseURL    *url.URL
	apiKey     string
	httpClient *http.Client
}

// NovuRESTOptions configures NovuRESTClient.
type NovuRESTOptions struct {
	// BaseURL is the Novu API root, e.g. http://localhost:3000.
	BaseURL string
	// APIKey is the per-Deployment Novu API key. Loaded from OpenBao KV.
	APIKey string
	// HTTPClient is optional; defaults to a 30s-timeout client.
	HTTPClient *http.Client
}

// NewNovuRESTClient constructs a client.
func NewNovuRESTClient(opts NovuRESTOptions) (*NovuRESTClient, error) {
	if strings.TrimSpace(opts.BaseURL) == "" {
		return nil, errors.New("notifications: novu base URL required")
	}
	if strings.TrimSpace(opts.APIKey) == "" {
		return nil, errors.New("notifications: novu API key required")
	}
	u, err := url.Parse(opts.BaseURL)
	if err != nil {
		return nil, fmt.Errorf("notifications: parse novu base URL: %w", err)
	}
	hc := opts.HTTPClient
	if hc == nil {
		hc = &http.Client{Timeout: 30 * time.Second}
	}
	return &NovuRESTClient{baseURL: u, apiKey: opts.APIKey, httpClient: hc}, nil
}

// triggerEventRequest mirrors POST /v1/events/trigger. We omit Novu's
// "topic" / "actor" features in MVP since neither MVP workflow needs them.
type triggerEventRequest struct {
	Name      string         `json:"name"`
	To        triggerTarget  `json:"to"`
	Payload   map[string]any `json:"payload,omitempty"`
	Overrides map[string]any `json:"overrides,omitempty"`
}

type triggerTarget struct {
	SubscriberID string `json:"subscriberId"`
}

type triggerEventResponse struct {
	Data struct {
		Acknowledged  bool   `json:"acknowledged"`
		Status        string `json:"status"`
		TransactionID string `json:"transactionId"`
	} `json:"data"`
}

// TriggerWorkflow implements NovuClient.TriggerWorkflow.
func (c *NovuRESTClient) TriggerWorkflow(ctx context.Context, novuWorkflowID, novuSubscriberID string, payload map[string]any) (string, error) {
	body := triggerEventRequest{
		Name:    novuWorkflowID,
		To:      triggerTarget{SubscriberID: novuSubscriberID},
		Payload: payload,
	}
	var out triggerEventResponse
	if err := c.do(ctx, http.MethodPost, "/v1/events/trigger", body, &out); err != nil {
		return "", err
	}
	if out.Data.TransactionID == "" {
		return "", fmt.Errorf("%w: novu acknowledged trigger but returned empty transaction id", ErrProviderUnavailable)
	}
	return out.Data.TransactionID, nil
}

type novuNotificationResponse struct {
	Data struct {
		ID            string `json:"_id"`
		TransactionID string `json:"transactionId"`
		Status        string `json:"status"`
		// The full Notification entity has many fields; we only consume status.
	} `json:"data"`
}

// GetTransactionStatus implements NovuClient.GetTransactionStatus. Novu's
// notification status strings ("queued", "sent", "completed", "error") map
// onto the platform's enum.
func (c *NovuRESTClient) GetTransactionStatus(ctx context.Context, transactionID string) (NotificationStatus, error) {
	path := "/v1/notifications/" + url.PathEscape(transactionID)
	var out novuNotificationResponse
	if err := c.do(ctx, http.MethodGet, path, nil, &out); err != nil {
		return "", err
	}
	switch strings.ToLower(out.Data.Status) {
	case "queued", "pending":
		return NotificationStatusQueued, nil
	case "sent":
		return NotificationStatusSent, nil
	case "completed", "delivered":
		return NotificationStatusDelivered, nil
	case "error", "failed":
		return NotificationStatusFailed, nil
	default:
		return NotificationStatusQueued, nil
	}
}

type novuIntegrationCreateRequest struct {
	ProviderID  string         `json:"providerId"`
	Channel     string         `json:"channel"`
	Credentials map[string]any `json:"credentials"`
	Active      bool           `json:"active"`
}

type novuIntegrationCreateResponse struct {
	Data struct {
		ID         string `json:"_id"`
		ProviderID string `json:"providerId"`
	} `json:"data"`
}

// UpsertIntegration implements NovuClient.UpsertIntegration. Novu's API
// uses POST /v1/integrations for create and PUT /v1/integrations/{id} for
// update; we branch on novuIntegrationID.
func (c *NovuRESTClient) UpsertIntegration(ctx context.Context, novuIntegrationID string, provider ChannelProvider, credentials map[string]any) (string, error) {
	novuProvider, channel := novuProviderAndChannel(provider)
	body := novuIntegrationCreateRequest{
		ProviderID:  novuProvider,
		Channel:     channel,
		Credentials: credentials,
		Active:      true,
	}
	if novuIntegrationID == "" {
		var out novuIntegrationCreateResponse
		if err := c.do(ctx, http.MethodPost, "/v1/integrations", body, &out); err != nil {
			return "", err
		}
		return out.Data.ID, nil
	}
	// Update path: Novu's PUT does not require providerId/channel — they're
	// fixed on the integration. We still send credentials + active.
	updateBody := map[string]any{
		"credentials": credentials,
		"active":      true,
	}
	var out novuIntegrationCreateResponse
	path := "/v1/integrations/" + url.PathEscape(novuIntegrationID)
	if err := c.do(ctx, http.MethodPut, path, updateBody, &out); err != nil {
		return "", err
	}
	if out.Data.ID == "" {
		return novuIntegrationID, nil
	}
	return out.Data.ID, nil
}

type novuSubscriberCreateRequest struct {
	SubscriberID string `json:"subscriberId"`
	Email        string `json:"email,omitempty"`
	FirstName    string `json:"firstName,omitempty"`
}

// EnsureSubscriber implements NovuClient.EnsureSubscriber. Novu's POST
// /v1/subscribers is idempotent on subscriberId — re-posting an existing
// id just updates the attributes.
func (c *NovuRESTClient) EnsureSubscriber(ctx context.Context, novuSubscriberID, email, name string) error {
	body := novuSubscriberCreateRequest{
		SubscriberID: novuSubscriberID,
		Email:        email,
		FirstName:    name,
	}
	// Discard response body; idempotent create.
	return c.do(ctx, http.MethodPost, "/v1/subscribers", body, nil)
}

// novuProviderAndChannel maps the platform's ChannelProvider onto Novu's
// (providerId, channel) tuple. Novu's SMTP integration is "nodemailer".
func novuProviderAndChannel(p ChannelProvider) (string, string) {
	switch p {
	case ProviderSMTP:
		return "nodemailer", "email"
	case ProviderSendGrid:
		return "sendgrid", "email"
	case ProviderSES:
		return "ses", "email"
	case ProviderInApp:
		return "novu", "in_app"
	}
	return "", ""
}

// do performs an authenticated HTTP request and decodes the JSON response
// when out is non-nil. Non-2xx responses surface as ErrProviderUnavailable
// joined with the upstream status text — callers wanting finer granularity
// can branch on the error message but should not parse it.
func (c *NovuRESTClient) do(ctx context.Context, method, path string, in any, out any) error {
	u := *c.baseURL
	u.Path = strings.TrimRight(u.Path, "/") + path
	var body io.Reader
	if in != nil {
		b, err := json.Marshal(in)
		if err != nil {
			return fmt.Errorf("notifications: marshal novu request: %w", err)
		}
		body = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, u.String(), body)
	if err != nil {
		return fmt.Errorf("notifications: build novu request: %w", err)
	}
	req.Header.Set("Authorization", "ApiKey "+c.apiKey)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("%w: %w", ErrProviderUnavailable, err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode >= 300 {
		buf, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<10))
		return fmt.Errorf("%w: novu returned %d: %s", ErrProviderUnavailable, resp.StatusCode, string(buf))
	}
	if out == nil {
		_, _ = io.Copy(io.Discard, resp.Body)
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}
