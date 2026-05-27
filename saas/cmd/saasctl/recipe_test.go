// Phase 15 — recipe command tests.
//
// Recipes are embedded at compile time via go:embed. These tests
// guarantee that:
//
//   - every §21 first-class workflow has a corresponding recipe file
//   - the markdown follows the agreed template (When to use,
//     Prerequisites, CLI, curl, TS SDK, Go SDK, Common pitfalls)
//   - lookupRecipe handles exact match, fuzzy match, and ambiguity
//     consistently
//
// We intentionally do NOT shell out to `saasctl recipe show` — the
// embed.FS is constructed at compile time so unit tests can read it
// directly via the same helpers the runtime uses.

package main

import (
	"strings"
	"testing"
)

// Per AGENTS.md §21, the first-class workflow recipes shipped in MVP.
// Keep this list in sync when §21 changes; the test will fail if any
// recipe file is missing.
var requiredRecipes = []string{
	"provision-deployment",
	"create-tenant",
	"invite-member",
	"assign-role",
	"check-authorization",
	"create-api-key",
	"view-audit-events",
	"send-notification",
	"link-social-provider",
	"attach-custom-domain",
}

// Sections every recipe MUST contain (markdown headings or fenced
// labels we agreed on in the plan).
var requiredSections = []string{
	"## When to use",
	"## Prerequisites",
	"## CLI",
	"## curl",
	"## TS SDK",
	"## Go SDK",
	"## Common pitfalls",
}

func TestEveryRequiredRecipeExists(t *testing.T) {
	got, err := listRecipes()
	if err != nil {
		t.Fatalf("listRecipes: %v", err)
	}
	have := map[string]bool{}
	for _, n := range got {
		have[n] = true
	}
	for _, want := range requiredRecipes {
		if !have[want] {
			t.Errorf("missing required recipe %q", want)
		}
	}
}

func TestEachRecipeHasRequiredSections(t *testing.T) {
	for _, name := range requiredRecipes {
		body, _, err := readRecipe(name)
		if err != nil {
			t.Errorf("read %s: %v", name, err)
			continue
		}
		md := string(body)
		for _, section := range requiredSections {
			if !strings.Contains(md, section) {
				t.Errorf("recipe %s missing section %q", name, section)
			}
		}
	}
}

func TestNoRecipeReferencesDeferredFeatures(t *testing.T) {
	// AGENTS.md §15 lists the explicit MVP scope cuts. Recipes must
	// not promise these — they are out of MVP scope and will mislead
	// callers if the recipe says "use newsletters/files/webhooks".
	deferred := []string{
		"newsletters",
		"upload a file",
		"register a webhook endpoint",
		"feature flags",
		"usage metering",
	}
	for _, name := range requiredRecipes {
		body, _, err := readRecipe(name)
		if err != nil {
			t.Errorf("read %s: %v", name, err)
			continue
		}
		md := strings.ToLower(string(body))
		for _, d := range deferred {
			if strings.Contains(md, strings.ToLower(d)) {
				t.Errorf("recipe %s references deferred feature %q", name, d)
			}
		}
	}
}

func TestLookupRecipe_ExactMatch(t *testing.T) {
	body, name, err := lookupRecipe("create-tenant")
	if err != nil {
		t.Fatalf("lookupRecipe: %v", err)
	}
	if name != "create-tenant" {
		t.Errorf("got %q want %q", name, "create-tenant")
	}
	if !strings.Contains(string(body), "## When to use") {
		t.Errorf("body looks truncated: %d bytes", len(body))
	}
}

func TestLookupRecipe_FuzzySingleMatch(t *testing.T) {
	_, name, err := lookupRecipe("audit")
	if err != nil {
		t.Fatalf("fuzzy lookup: %v", err)
	}
	if name != "view-audit-events" {
		t.Errorf("expected view-audit-events, got %q", name)
	}
}

func TestLookupRecipe_AmbiguousFuzzyMatch(t *testing.T) {
	_, _, err := lookupRecipe("create") // matches create-tenant + create-api-key
	if err == nil {
		t.Fatalf("expected ambiguity error, got nil")
	}
	if !strings.Contains(err.Error(), "ambiguous") {
		t.Errorf("expected ambiguity message, got %v", err)
	}
}

func TestLookupRecipe_NotFound(t *testing.T) {
	_, _, err := lookupRecipe("does-not-exist")
	if err == nil {
		t.Fatalf("expected not-found error, got nil")
	}
	if !strings.Contains(err.Error(), "no recipe matches") {
		t.Errorf("expected not-found message, got %v", err)
	}
}
