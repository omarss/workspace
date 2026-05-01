// Package together implements llm.Provider against the Together.ai
// chat-completions API (https://docs.together.ai/reference/chat-completions).
//
// The endpoint is OpenAI-compatible, so the wire shape stays small and we
// keep the dependency-free stdlib net/http path.
package together

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/omarss/prompter/pkg/llm"
)

// DefaultEndpoint is overridden in tests via NewWithEndpoint.
const DefaultEndpoint = "https://api.together.xyz"

// Client is safe for concurrent use.
type Client struct {
	apiKey   string
	endpoint string
	http     *http.Client
}

// New returns a client against the production endpoint.
func New(apiKey string) *Client {
	return NewWithEndpoint(apiKey, DefaultEndpoint, nil)
}

// NewWithEndpoint is the test-friendly constructor. h=nil falls back to a
// 60s timeout — generous for the larger models on Together.
func NewWithEndpoint(apiKey, endpoint string, h *http.Client) *Client {
	if h == nil {
		h = &http.Client{Timeout: 60 * time.Second}
	}
	return &Client{apiKey: apiKey, endpoint: endpoint, http: h}
}

// wireMessage / wireRequest mirror the OpenAI-compatible JSON shape Together
// expects. We don't share the llm.Message type directly because we want to
// control field names + json tags here without coupling the public package.
type wireMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type wireRequest struct {
	Model       string        `json:"model"`
	Messages    []wireMessage `json:"messages"`
	Temperature float64       `json:"temperature"`
	Seed        int64         `json:"seed,omitempty"`
	MaxTokens   int           `json:"max_tokens,omitempty"`
}

type wireUsage struct {
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
}

type wireChoice struct {
	Message wireMessage `json:"message"`
}

type wireResponse struct {
	Choices []wireChoice `json:"choices"`
	Usage   wireUsage    `json:"usage"`
}

type wireError struct {
	Error struct {
		Message string `json:"message"`
		Type    string `json:"type"`
	} `json:"error"`
}

// Chat satisfies llm.Provider.
func (c *Client) Chat(ctx context.Context, req llm.Request) (llm.Response, error) {
	wreq := wireRequest{
		Model:       req.Model,
		Messages:    make([]wireMessage, 0, len(req.Messages)),
		Temperature: req.Temperature,
		Seed:        req.Seed,
		MaxTokens:   req.MaxTokens,
	}
	for _, m := range req.Messages {
		wreq.Messages = append(wreq.Messages, wireMessage{Role: string(m.Role), Content: m.Content})
	}

	buf, err := json.Marshal(wreq)
	if err != nil {
		return llm.Response{}, fmt.Errorf("marshal: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost,
		c.endpoint+"/v1/chat/completions", bytes.NewReader(buf))
	if err != nil {
		return llm.Response{}, fmt.Errorf("new request: %w", err)
	}
	httpReq.Header.Set("Authorization", "Bearer "+c.apiKey)
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.http.Do(httpReq)
	if err != nil {
		return llm.Response{}, fmt.Errorf("post: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		var er wireError
		if json.Unmarshal(body, &er) == nil && er.Error.Message != "" {
			return llm.Response{}, fmt.Errorf("together %d: %s", resp.StatusCode, er.Error.Message)
		}
		return llm.Response{}, fmt.Errorf("together %d: %s", resp.StatusCode, string(body))
	}

	var out wireResponse
	if err := json.Unmarshal(body, &out); err != nil {
		return llm.Response{}, fmt.Errorf("decode: %w", err)
	}
	if len(out.Choices) == 0 {
		return llm.Response{}, fmt.Errorf("together: no choices in response")
	}
	return llm.Response{
		Content:      out.Choices[0].Message.Content,
		PromptTokens: out.Usage.PromptTokens,
		OutputTokens: out.Usage.CompletionTokens,
	}, nil
}
