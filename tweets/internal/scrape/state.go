package scrape

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

// Cookies is the cookie jar persisted by the CDP refresher
// (/srv/tweets/cookies.json). The two flat fields (auth_token / ct0)
// are convenience accessors; the full `All` array is what gets serialised
// into the Cookie request header, including HttpOnly cookies that the
// browser would normally hide from JS but CDP exposes.
type Cookies struct {
	AuthToken string         `json:"auth_token"`
	CT0       string         `json:"ct0"`
	All       []NamedCookie  `json:"all"`
}

type NamedCookie struct {
	Name   string `json:"name"`
	Value  string `json:"value"`
	Domain string `json:"domain,omitempty"`
}

// CookieHeader returns a `; `-joined Cookie header value that mirrors
// what the browser sends. Empty jar → empty string (caller decides
// whether that's fatal).
func (c Cookies) CookieHeader() string {
	if len(c.All) == 0 {
		return ""
	}
	parts := make([]string, 0, len(c.All))
	for _, k := range c.All {
		parts = append(parts, k.Name+"="+k.Value)
	}
	return strings.Join(parts, "; ")
}

// LoadCookies reads /srv/tweets/cookies.json (or any path). Missing
// file is a soft error; malformed JSON / empty critical cookies are
// hard so the caller fails loudly instead of getting blank scrapes.
func LoadCookies(path string) (Cookies, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return Cookies{}, fmt.Errorf("read cookies %q: %w", path, err)
	}
	var c Cookies
	if err := json.Unmarshal(raw, &c); err != nil {
		return Cookies{}, fmt.Errorf("parse cookies %q: %w", path, err)
	}
	if c.AuthToken == "" || c.CT0 == "" {
		return Cookies{}, fmt.Errorf("cookies %q missing auth_token or ct0", path)
	}
	return c, nil
}

// SearchTemplate is the per-endpoint signature the CDP refresher
// captures from a real browser navigation. Fields:
//   QueryID   — the per-operation hash on the GraphQL URL path.
//   URL       — the original captured URL; we keep it for the
//               features query param verbatim (X validates features
//               byte-for-byte against the JS bundle).
//   Headers   — the captured browser headers, including the X-Client-
//               Transaction-Id signature. We never mutate this map.
//   CapturedAt — when the refresher ran; used to surface staleness.
type SearchTemplate struct {
	URL        string            `json:"url"`
	QueryID    string            `json:"query_id"`
	Method     string            `json:"method"`
	Headers    map[string]string `json:"headers"`
	UserID     string            `json:"user_id,omitempty"`
	CapturedAt string            `json:"captured_at"`
}

// LoadTemplate reads /srv/tweets/search-template.json. Empty fields
// fail loudly so a stale template doesn't silently degrade scrapes.
func LoadTemplate(path string) (SearchTemplate, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return SearchTemplate{}, fmt.Errorf("read template %q: %w", path, err)
	}
	var t SearchTemplate
	if err := json.Unmarshal(raw, &t); err != nil {
		return SearchTemplate{}, fmt.Errorf("parse template %q: %w", path, err)
	}
	if t.QueryID == "" || t.URL == "" {
		return SearchTemplate{}, fmt.Errorf("template %q missing query_id or url", path)
	}
	return t, nil
}
