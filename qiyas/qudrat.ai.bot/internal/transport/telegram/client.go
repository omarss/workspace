package telegram

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"time"
)

// Client is a stdlib-only Telegram Bot API client. Safe for concurrent use.
type Client struct {
	token      string
	endpoint   string
	httpClient *http.Client
}

// New constructs a client. h=nil falls back to a 60s default — long-poll
// uses an even longer timeout per call below.
func New(token string, h *http.Client) *Client {
	if h == nil {
		h = &http.Client{Timeout: 60 * time.Second}
	}
	return &Client{
		token:      token,
		endpoint:   "https://api.telegram.org",
		httpClient: h,
	}
}

func (c *Client) url(method string) string {
	return fmt.Sprintf("%s/bot%s/%s", c.endpoint, c.token, method)
}

// envelope is the standard `{ok, result}` Telegram returns.
type envelope[T any] struct {
	OK          bool   `json:"ok"`
	Description string `json:"description"`
	Result      T      `json:"result"`
}

// GetUpdates long-polls for new updates. timeoutSecs is server-side wait
// (Telegram-side); the http.Client timeout must exceed it.
func (c *Client) GetUpdates(ctx context.Context, offset int64, timeoutSecs int) ([]Update, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		c.url("getUpdates")+
			"?timeout="+strconv.Itoa(timeoutSecs)+
			"&offset="+strconv.FormatInt(offset, 10), nil)
	if err != nil {
		return nil, fmt.Errorf("new request: %w", err)
	}
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("get: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	var env envelope[[]Update]
	if err := json.Unmarshal(raw, &env); err != nil {
		return nil, fmt.Errorf("decode: %w", err)
	}
	if !env.OK {
		return nil, fmt.Errorf("telegram getUpdates: %s", env.Description)
	}
	return env.Result, nil
}

// SendMessage posts a text message + optional inline keyboard.
func (c *Client) SendMessage(ctx context.Context, req SendMessageReq) error {
	return c.postNoResult(ctx, "sendMessage", req)
}

// SendPoll posts a quiz poll and returns the poll_id we use to correlate
// poll_answer updates back to an item.
func (c *Client) SendPoll(ctx context.Context, req SendPollReq) (string, error) {
	body, _ := json.Marshal(req)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.url("sendPoll"), bytes.NewReader(body))
	if err != nil {
		return "", fmt.Errorf("new request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return "", fmt.Errorf("post: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	var out SendPollResp
	if err := json.Unmarshal(raw, &out); err != nil {
		return "", fmt.Errorf("decode: %w", err)
	}
	if !out.OK {
		return "", fmt.Errorf("telegram sendPoll: %s", string(raw))
	}
	return out.Result.Poll.ID, nil
}

// AnswerCallbackQuery acknowledges an inline-button press so the spinner
// stops on the user's device.
func (c *Client) AnswerCallbackQuery(ctx context.Context, req AnswerCallbackQueryReq) error {
	return c.postNoResult(ctx, "answerCallbackQuery", req)
}

func (c *Client) postNoResult(ctx context.Context, method string, body any) error {
	buf, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.url(method), bytes.NewReader(buf))
	if err != nil {
		return fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("post: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 16<<10))
	var env envelope[json.RawMessage]
	if err := json.Unmarshal(raw, &env); err != nil {
		return fmt.Errorf("decode: %w", err)
	}
	if !env.OK {
		return fmt.Errorf("telegram %s: %s", method, env.Description)
	}
	return nil
}
