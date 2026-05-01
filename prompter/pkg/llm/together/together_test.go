package together

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/omarss/prompter/pkg/llm"
)

func TestChat_PostsExpectedPayload(t *testing.T) {
	t.Parallel()

	var captured wireRequest
	var capturedAuth, capturedPath string

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedPath = r.URL.Path
		capturedAuth = r.Header.Get("Authorization")
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &captured)
		_, _ = w.Write([]byte(`{
			"choices":[{"message":{"role":"assistant","content":"def f(): pass"}}],
			"usage":{"prompt_tokens":12,"completion_tokens":4}
		}`))
	}))
	t.Cleanup(srv.Close)

	c := NewWithEndpoint("tk_test", srv.URL, srv.Client())
	resp, err := c.Chat(context.Background(), llm.Request{
		Model: "Qwen/Qwen2.5-Coder-7B-Instruct",
		Messages: []llm.Message{
			{Role: llm.RoleSystem, Content: "You are concise."},
			{Role: llm.RoleUser, Content: "Empty function"},
		},
		Temperature: 0,
		Seed:        42,
		MaxTokens:   256,
	})
	if err != nil {
		t.Fatalf("chat: %v", err)
	}

	if capturedPath != "/v1/chat/completions" {
		t.Errorf("path = %q", capturedPath)
	}
	if capturedAuth != "Bearer tk_test" {
		t.Errorf("auth = %q", capturedAuth)
	}
	if captured.Model != "Qwen/Qwen2.5-Coder-7B-Instruct" {
		t.Errorf("model = %q", captured.Model)
	}
	if len(captured.Messages) != 2 || captured.Messages[1].Content != "Empty function" {
		t.Errorf("messages = %+v", captured.Messages)
	}
	if captured.Seed != 42 || captured.MaxTokens != 256 {
		t.Errorf("seed/max_tokens not forwarded: %+v", captured)
	}
	if resp.Content != "def f(): pass" {
		t.Errorf("content = %q", resp.Content)
	}
	if resp.PromptTokens != 12 || resp.OutputTokens != 4 {
		t.Errorf("usage = %+v", resp)
	}
}

func TestChat_SurfacesAPIError(t *testing.T) {
	t.Parallel()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"error":{"message":"unknown model","type":"invalid_request_error"}}`))
	}))
	t.Cleanup(srv.Close)

	c := NewWithEndpoint("k", srv.URL, srv.Client())
	_, err := c.Chat(context.Background(), llm.Request{
		Model:    "does-not-exist",
		Messages: []llm.Message{{Role: llm.RoleUser, Content: "x"}},
	})
	if err == nil {
		t.Fatalf("expected error")
	}
	if !strings.Contains(err.Error(), "unknown model") {
		t.Errorf("err should include API message; got %v", err)
	}
}

func TestChat_NoChoices_ReturnsError(t *testing.T) {
	t.Parallel()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"choices":[],"usage":{}}`))
	}))
	t.Cleanup(srv.Close)

	c := NewWithEndpoint("k", srv.URL, srv.Client())
	_, err := c.Chat(context.Background(), llm.Request{
		Model:    "x",
		Messages: []llm.Message{{Role: llm.RoleUser, Content: "x"}},
	})
	if err == nil {
		t.Fatalf("expected error")
	}
}
