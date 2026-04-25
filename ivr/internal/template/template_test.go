package template_test

import (
	"errors"
	"strings"
	"testing"

	"github.com/omarss/ivr/internal/template"
)

const minimalValid = `
name: support-l1
version: 1
language_default: ar
languages_allowed: [ar, en]
voice:
  ar: { provider: azure, name: ar-SA-HamedNeural }
  en: { provider: piper, name: en_US-ryan-high }
  fallback: piper
opening:
  ar: "السلام عليكم"
  en: "Hello"
system_prompt: |
  You are an L1 support agent.
policies:
  consent_prompt: required
  recording: disabled
  max_silence_ms: 4000
  max_call_seconds: 600
  barge_in: true
  amd:
    action: hangup_if_voicemail
`

func mustParse(t *testing.T, src string) *template.Template {
	t.Helper()
	tpl, err := template.Parse([]byte(src))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	return tpl
}

func TestParse_MinimalValid(t *testing.T) {
	tpl := mustParse(t, minimalValid)
	if tpl.Name != "support-l1" {
		t.Errorf("Name = %q", tpl.Name)
	}
	if tpl.Version != 1 {
		t.Errorf("Version = %d", tpl.Version)
	}
	if tpl.LanguageDefault != "ar" {
		t.Errorf("LanguageDefault = %q", tpl.LanguageDefault)
	}
	if len(tpl.LanguagesAllowed) != 2 {
		t.Errorf("LanguagesAllowed = %v", tpl.LanguagesAllowed)
	}
	if tpl.Voice["ar"].Provider != "azure" {
		t.Errorf("Voice[ar].Provider = %q", tpl.Voice["ar"].Provider)
	}
	if tpl.VoiceFallback != "piper" {
		t.Errorf("VoiceFallback = %q", tpl.VoiceFallback)
	}
	if !tpl.Policies.BargeIn {
		t.Error("Policies.BargeIn = false")
	}
	if tpl.ContentHash == "" {
		t.Error("ContentHash empty")
	}
}

func TestParse_RejectsEmpty(t *testing.T) {
	_, err := template.Parse(nil)
	if !errors.Is(err, template.ErrEmpty) {
		t.Fatalf("expected ErrEmpty, got %v", err)
	}
	_, err = template.Parse([]byte("   \n  "))
	if !errors.Is(err, template.ErrEmpty) {
		t.Fatalf("expected ErrEmpty, got %v", err)
	}
}

func TestParse_RejectsMalformedYAML(t *testing.T) {
	_, err := template.Parse([]byte("name: : :\n  bogus\nversion"))
	if err == nil {
		t.Fatal("expected error on malformed yaml")
	}
}

func TestParse_RejectsMissingName(t *testing.T) {
	src := strings.Replace(minimalValid, "name: support-l1", "name: \"\"", 1)
	_, err := template.Parse([]byte(src))
	if !errors.Is(err, template.ErrMissingName) {
		t.Fatalf("expected ErrMissingName, got %v", err)
	}
}

func TestParse_RejectsZeroVersion(t *testing.T) {
	src := strings.Replace(minimalValid, "version: 1", "version: 0", 1)
	_, err := template.Parse([]byte(src))
	if !errors.Is(err, template.ErrInvalidVersion) {
		t.Fatalf("expected ErrInvalidVersion, got %v", err)
	}
}

func TestParse_RejectsLanguageDefaultNotAllowed(t *testing.T) {
	src := strings.Replace(minimalValid, "language_default: ar", "language_default: fr", 1)
	_, err := template.Parse([]byte(src))
	if !errors.Is(err, template.ErrLanguageDefaultNotAllowed) {
		t.Fatalf("expected ErrLanguageDefaultNotAllowed, got %v", err)
	}
}

func TestParse_RejectsMissingVoiceWithoutFallback(t *testing.T) {
	src := `
name: t
version: 1
language_default: ar
languages_allowed: [ar, en]
voice:
  ar: { provider: azure, name: ar-SA-HamedNeural }
opening:
  ar: hi
  en: hi
system_prompt: x
policies:
  consent_prompt: optional
  recording: disabled
  max_silence_ms: 1000
  max_call_seconds: 60
  barge_in: false
  amd: { action: ignore }
`
	_, err := template.Parse([]byte(src))
	if !errors.Is(err, template.ErrMissingVoice) {
		t.Fatalf("expected ErrMissingVoice, got %v", err)
	}
}

func TestParse_AcceptsMissingVoiceWithFallback(t *testing.T) {
	src := `
name: t
version: 1
language_default: ar
languages_allowed: [ar, en]
voice:
  ar: { provider: azure, name: ar-SA-HamedNeural }
  fallback: piper
opening:
  ar: hi
  en: hi
system_prompt: x
policies:
  consent_prompt: optional
  recording: disabled
  max_silence_ms: 1000
  max_call_seconds: 60
  barge_in: false
  amd: { action: ignore }
`
	tpl := mustParse(t, src)
	if tpl.VoiceFallback != "piper" {
		t.Fatalf("VoiceFallback = %q", tpl.VoiceFallback)
	}
}

func TestParse_RejectsMissingOpening(t *testing.T) {
	src := strings.Replace(minimalValid, "  en: \"Hello\"\n", "", 1)
	_, err := template.Parse([]byte(src))
	if !errors.Is(err, template.ErrMissingOpening) {
		t.Fatalf("expected ErrMissingOpening, got %v", err)
	}
}

func TestParse_RejectsInvalidToolURL(t *testing.T) {
	src := minimalValid + `
tools:
  - name: lookup
    url: "not a url"
    description: x
`
	_, err := template.Parse([]byte(src))
	if !errors.Is(err, template.ErrInvalidToolURL) {
		t.Fatalf("expected ErrInvalidToolURL, got %v", err)
	}
}

func TestParse_RejectsDuplicateToolNames(t *testing.T) {
	src := minimalValid + `
tools:
  - name: lookup
    url: https://example.com
    description: x
  - name: lookup
    url: https://example.com
    description: y
`
	_, err := template.Parse([]byte(src))
	if !errors.Is(err, template.ErrDuplicateToolName) {
		t.Fatalf("expected ErrDuplicateToolName, got %v", err)
	}
}

func TestParse_RejectsInvalidConsentPrompt(t *testing.T) {
	src := strings.Replace(minimalValid, "consent_prompt: required", "consent_prompt: maybe", 1)
	_, err := template.Parse([]byte(src))
	if !errors.Is(err, template.ErrInvalidPolicy) {
		t.Fatalf("expected ErrInvalidPolicy, got %v", err)
	}
}

func TestParse_RejectsInvalidAMDAction(t *testing.T) {
	src := strings.Replace(minimalValid, "action: hangup_if_voicemail", "action: dance", 1)
	_, err := template.Parse([]byte(src))
	if !errors.Is(err, template.ErrInvalidPolicy) {
		t.Fatalf("expected ErrInvalidPolicy, got %v", err)
	}
}

func TestParse_ContentHashIsDeterministic(t *testing.T) {
	a := mustParse(t, minimalValid)
	b := mustParse(t, minimalValid)
	if a.ContentHash != b.ContentHash {
		t.Fatalf("hash drift: %s vs %s", a.ContentHash, b.ContentHash)
	}
}

func TestParse_ContentHashChangesWithBody(t *testing.T) {
	a := mustParse(t, minimalValid)
	other := strings.Replace(minimalValid, "max_silence_ms: 4000", "max_silence_ms: 5000", 1)
	b := mustParse(t, other)
	if a.ContentHash == b.ContentHash {
		t.Fatalf("hash should change but didn't: %s", a.ContentHash)
	}
}

func TestVoiceFor_FallsBackWhenLanguageMissing(t *testing.T) {
	src := `
name: t
version: 1
language_default: ar
languages_allowed: [ar, en]
voice:
  ar: { provider: azure, name: ar-SA-HamedNeural }
  fallback: piper
opening: { ar: hi, en: hi }
system_prompt: x
policies:
  consent_prompt: optional
  recording: disabled
  max_silence_ms: 1000
  max_call_seconds: 60
  barge_in: false
  amd: { action: ignore }
`
	tpl := mustParse(t, src)
	v, ok := tpl.VoiceFor("en")
	if !ok {
		t.Fatal("VoiceFor(en) ok=false")
	}
	if v.Provider != "piper" {
		t.Fatalf("VoiceFor(en).Provider = %q", v.Provider)
	}
	if v.Name == "" {
		t.Error("fallback voice name empty")
	}
}

func TestVoiceFor_ExactMatch(t *testing.T) {
	tpl := mustParse(t, minimalValid)
	v, ok := tpl.VoiceFor("ar")
	if !ok || v.Provider != "azure" || v.Name != "ar-SA-HamedNeural" {
		t.Fatalf("VoiceFor(ar) = %+v ok=%v", v, ok)
	}
}

func TestVoiceFor_UnknownLanguageWithoutFallback(t *testing.T) {
	src := strings.Replace(minimalValid, "  fallback: piper\n", "", 1)
	tpl := mustParse(t, src)
	_, ok := tpl.VoiceFor("zh")
	if ok {
		t.Fatal("expected ok=false for unknown language without fallback")
	}
}
