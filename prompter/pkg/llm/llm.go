// Package llm defines the provider-agnostic chat completion contract used
// by the prompter inference flow. Providers (Together.ai today, OpenAI/
// Anthropic later if we add a frontier tier) live in subpackages and
// implement Provider.
//
// Keeping the interface small lets the inference service stay free of
// vendor-specific types — the "no vendor SDK leaks" workspace rule.
package llm

import "context"

// Role enumerates the OpenAI/Anthropic-style chat roles. We don't model
// "tool" or "function" roles yet; submissions are single-turn user prompts.
type Role string

// Standard roles a Provider must accept.
const (
	RoleSystem    Role = "system"
	RoleUser      Role = "user"
	RoleAssistant Role = "assistant"
)

// Message is a single chat turn.
type Message struct {
	Role    Role
	Content string
}

// Request bundles the parameters of a single chat completion. Temperature
// defaults to 0 across the game so submissions are deterministic; the seed
// pins sampling for the rare provider that doesn't honor temp=0 strictly.
type Request struct {
	Model       string
	Messages    []Message
	Temperature float64
	Seed        int64
	MaxTokens   int
}

// Response is what a provider returns after a successful completion.
type Response struct {
	Content      string
	PromptTokens int
	OutputTokens int
}

// Provider is the seam between inference logic and a specific vendor.
type Provider interface {
	Chat(ctx context.Context, req Request) (Response, error)
}
