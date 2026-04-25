// Package template parses and validates tenant conversation templates.
//
// A template is the heart of the product — it owns the agent's system prompt,
// per-language voices, opening line, allowed tool calls, and runtime policies
// (consent, recording, barge-in, AMD). Templates are content-addressed via
// ContentHash so a published version is immutable: any change produces a new
// version with a new hash, and in-flight calls keep referencing the version
// they started with.
package template

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strings"

	"gopkg.in/yaml.v3"
)

// Template is the validated, normalized form of a tenant's template document.
type Template struct {
	Name             string                 `json:"name"             yaml:"name"`
	Version          int                    `json:"version"          yaml:"version"`
	LanguageDefault  string                 `json:"language_default" yaml:"language_default"`
	LanguagesAllowed []string               `json:"languages_allowed" yaml:"languages_allowed"`
	Voice            map[string]VoiceConfig `json:"voice"            yaml:"-"`
	VoiceFallback    string                 `json:"voice_fallback,omitempty" yaml:"-"`
	Opening          map[string]string      `json:"opening"          yaml:"opening"`
	SystemPrompt     string                 `json:"system_prompt"    yaml:"system_prompt"`
	Tools            []Tool                 `json:"tools,omitempty"  yaml:"tools"`
	Policies         Policies               `json:"policies"         yaml:"policies"`
	Guardrails       Guardrails             `json:"guardrails,omitempty" yaml:"guardrails"`

	// ContentHash is sha256-hex over the canonical JSON encoding of all fields
	// except ContentHash itself.
	ContentHash string `json:"-" yaml:"-"`
}

// VoiceConfig identifies a TTS voice.
type VoiceConfig struct {
	Provider string `json:"provider" yaml:"provider"`
	Name     string `json:"name"     yaml:"name"`
}

// Tool is an HTTP endpoint the agent may call mid-conversation.
type Tool struct {
	Name        string `json:"name"        yaml:"name"`
	URL         string `json:"url"         yaml:"url"`
	Description string `json:"description" yaml:"description"`
	SchemaRef   string `json:"schema_ref,omitempty" yaml:"schema_ref"`
}

// Policies controls runtime call behavior.
type Policies struct {
	ConsentPrompt  string    `json:"consent_prompt"   yaml:"consent_prompt"`
	Recording      string    `json:"recording"        yaml:"recording"`
	MaxSilenceMs   int       `json:"max_silence_ms"   yaml:"max_silence_ms"`
	MaxCallSeconds int       `json:"max_call_seconds" yaml:"max_call_seconds"`
	BargeIn        bool      `json:"barge_in"         yaml:"barge_in"`
	AMD            AMDConfig `json:"amd"              yaml:"amd"`
}

// AMDConfig controls answering-machine detection behavior.
type AMDConfig struct {
	Action string `json:"action" yaml:"action"`
}

// Guardrails carries soft policies the agent enforces in-prompt.
type Guardrails struct {
	BlockedTopics []string            `json:"blocked_topics,omitempty" yaml:"blocked_topics"`
	ExitPhrases   map[string][]string `json:"exit_phrases,omitempty"   yaml:"exit_phrases"`
}

// Sentinel errors. Callers should branch on errors.Is.
var (
	ErrEmpty                     = errors.New("template: empty document")
	ErrMissingName               = errors.New("template: missing name")
	ErrInvalidVersion            = errors.New("template: version must be >= 1")
	ErrLanguageDefaultNotAllowed = errors.New("template: language_default not in languages_allowed")
	ErrMissingVoice              = errors.New("template: missing voice for allowed language with no fallback")
	ErrMissingOpening            = errors.New("template: missing opening for allowed language")
	ErrMissingSystemPrompt       = errors.New("template: missing system_prompt")
	ErrInvalidToolURL            = errors.New("template: invalid tool url")
	ErrDuplicateToolName         = errors.New("template: duplicate tool name")
	ErrInvalidPolicy             = errors.New("template: invalid policy value")
)

// rawTemplate is the on-the-wire shape; voice+fallback share a yaml key so
// they are unmarshalled separately.
type rawTemplate struct {
	Name             string               `yaml:"name"`
	Version          int                  `yaml:"version"`
	LanguageDefault  string               `yaml:"language_default"`
	LanguagesAllowed []string             `yaml:"languages_allowed"`
	Voice            map[string]yaml.Node `yaml:"voice"`
	Opening          map[string]string    `yaml:"opening"`
	SystemPrompt     string               `yaml:"system_prompt"`
	Tools            []Tool               `yaml:"tools"`
	Policies         Policies             `yaml:"policies"`
	Guardrails       Guardrails           `yaml:"guardrails"`
}

// Parse validates raw YAML bytes into a Template.
func Parse(data []byte) (*Template, error) {
	if len(strings.TrimSpace(string(data))) == 0 {
		return nil, ErrEmpty
	}

	var raw rawTemplate
	if err := yaml.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("template: yaml: %w", err)
	}

	tpl := &Template{
		Name:             strings.TrimSpace(raw.Name),
		Version:          raw.Version,
		LanguageDefault:  raw.LanguageDefault,
		LanguagesAllowed: raw.LanguagesAllowed,
		Opening:          raw.Opening,
		SystemPrompt:     strings.TrimSpace(raw.SystemPrompt),
		Tools:            raw.Tools,
		Policies:         raw.Policies,
		Guardrails:       raw.Guardrails,
		Voice:            map[string]VoiceConfig{},
	}

	// Pull out the optional `fallback` key from the voice map and decode the
	// rest as VoiceConfig.
	for k, node := range raw.Voice {
		if k == "fallback" {
			var s string
			if err := node.Decode(&s); err != nil {
				return nil, fmt.Errorf("template: voice.fallback: %w", err)
			}
			tpl.VoiceFallback = s
			continue
		}
		var vc VoiceConfig
		if err := node.Decode(&vc); err != nil {
			return nil, fmt.Errorf("template: voice.%s: %w", k, err)
		}
		tpl.Voice[k] = vc
	}

	if err := validate(tpl); err != nil {
		return nil, err
	}

	hash, err := computeHash(tpl)
	if err != nil {
		return nil, fmt.Errorf("template: hash: %w", err)
	}
	tpl.ContentHash = hash
	return tpl, nil
}

// VoiceFor returns the voice to use for the given language, falling back to
// the configured fallback provider with the language as the voice name when
// no exact match exists. Returns ok=false when neither path applies.
func (t *Template) VoiceFor(lang string) (VoiceConfig, bool) {
	if v, ok := t.Voice[lang]; ok {
		return v, true
	}
	if t.VoiceFallback != "" {
		return VoiceConfig{Provider: t.VoiceFallback, Name: defaultVoiceName(t.VoiceFallback, lang)}, true
	}
	return VoiceConfig{}, false
}

// defaultVoiceName picks a sensible default voice name per provider+language.
// Tenants with stricter needs should declare a per-language voice explicitly.
func defaultVoiceName(provider, lang string) string {
	switch provider {
	case "piper":
		switch lang {
		case "ar":
			return "ar_JO-kareem-medium"
		case "en":
			return "en_US-ryan-high"
		default:
			return "en_US-ryan-high"
		}
	case "azure":
		switch lang {
		case "ar":
			return "ar-SA-HamedNeural"
		case "en":
			return "en-US-AriaNeural"
		default:
			return "en-US-AriaNeural"
		}
	default:
		return ""
	}
}

func validate(t *Template) error {
	if t.Name == "" {
		return ErrMissingName
	}
	if t.Version < 1 {
		return ErrInvalidVersion
	}
	if !slices.Contains(t.LanguagesAllowed, t.LanguageDefault) {
		return ErrLanguageDefaultNotAllowed
	}
	if t.SystemPrompt == "" {
		return ErrMissingSystemPrompt
	}
	for _, lang := range t.LanguagesAllowed {
		if _, ok := t.Voice[lang]; !ok && t.VoiceFallback == "" {
			return fmt.Errorf("%w: %s", ErrMissingVoice, lang)
		}
		if _, ok := t.Opening[lang]; !ok {
			return fmt.Errorf("%w: %s", ErrMissingOpening, lang)
		}
	}

	seen := map[string]bool{}
	for _, tool := range t.Tools {
		if seen[tool.Name] {
			return fmt.Errorf("%w: %s", ErrDuplicateToolName, tool.Name)
		}
		seen[tool.Name] = true
		u, err := url.Parse(tool.URL)
		if err != nil || u.Scheme == "" || u.Host == "" || strings.Contains(tool.URL, " ") {
			return fmt.Errorf("%w: %s", ErrInvalidToolURL, tool.URL)
		}
	}

	switch t.Policies.ConsentPrompt {
	case "required", "optional", "disabled":
	default:
		return fmt.Errorf("%w: consent_prompt=%q", ErrInvalidPolicy, t.Policies.ConsentPrompt)
	}
	switch t.Policies.Recording {
	case "enabled", "disabled":
	default:
		return fmt.Errorf("%w: recording=%q", ErrInvalidPolicy, t.Policies.Recording)
	}
	switch t.Policies.AMD.Action {
	case "hangup_if_voicemail", "leave_message", "ignore":
	default:
		return fmt.Errorf("%w: amd.action=%q", ErrInvalidPolicy, t.Policies.AMD.Action)
	}
	if t.Policies.MaxSilenceMs <= 0 {
		return fmt.Errorf("%w: max_silence_ms must be > 0", ErrInvalidPolicy)
	}
	if t.Policies.MaxCallSeconds <= 0 {
		return fmt.Errorf("%w: max_call_seconds must be > 0", ErrInvalidPolicy)
	}
	return nil
}

// computeHash JSON-marshals the template (with ContentHash zeroed) and
// returns its sha256 hex digest. encoding/json sorts map keys alphabetically,
// so the output is deterministic.
func computeHash(t *Template) (string, error) {
	clone := *t
	clone.ContentHash = ""
	b, err := json.Marshal(&clone)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:]), nil
}
