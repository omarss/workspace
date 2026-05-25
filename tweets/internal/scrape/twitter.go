package scrape

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/omarss/workspace/tweets/internal/server"
)

// xBearer is the public bearer token x.com's own web client uses.
// It rotates rarely (last known change April 2025). When X rotates,
// `auth-token-rotated` shows up in the response body and our 401
// handling triggers a refresh.
//
// Note this is *not* a per-user secret — it's a fixed token X ships
// in its JS bundle. The user-bearing credential is the cookie jar.
const xBearer = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

// ErrAuthFailed is returned when X rejects our credentials with 401/403/404.
// The refresh loop treats this as a "kick the CDP refresher" signal — the
// TID or session probably went stale.
var ErrAuthFailed = errors.New("twitter auth rejected")

// HTTPScraper hits the live X SearchTimeline endpoint using cached
// cookies + template captured by the CDP refresher.
type HTTPScraper struct {
	cookiesPath  string
	templatePath string
	http         *http.Client

	mu     sync.RWMutex
	cookies Cookies
	tmpl    SearchTemplate
}

// NewHTTPScraper loads the initial credentials. Subsequent refreshes
// (when the operator runs the CDP refresher) are picked up by
// Reload — the scraper polls the mtime on the two files or can be
// nudged externally.
func NewHTTPScraper(cookiesPath, templatePath string) (*HTTPScraper, error) {
	s := &HTTPScraper{
		cookiesPath:  cookiesPath,
		templatePath: templatePath,
		http: &http.Client{
			Timeout: 15 * time.Second,
		},
	}
	if err := s.Reload(); err != nil {
		return nil, err
	}
	return s, nil
}

// Reload re-reads cookies + template from disk. Called by the refresh
// loop after invoking the CDP refresher; also at startup.
func (s *HTTPScraper) Reload() error {
	c, err := LoadCookies(s.cookiesPath)
	if err != nil {
		return err
	}
	t, err := LoadTemplate(s.templatePath)
	if err != nil {
		return err
	}
	s.mu.Lock()
	s.cookies = c
	s.tmpl = t
	s.mu.Unlock()
	return nil
}

// Search runs one SearchTimeline call for the given country. The
// query is `place_country:<CC> -is:retweet -filter:replies` — broad,
// returns every geo-tagged post; downstream scoring (spam + event)
// decides what surfaces. Latest (chronological) product ordering, so
// the same scrape across ticks returns deterministic new content.
func (s *HTTPScraper) Search(ctx context.Context, country server.Country, max int) ([]server.Tweet, error) {
	if max <= 0 {
		max = 30
	}
	s.mu.RLock()
	cookies, tmpl := s.cookies, s.tmpl
	s.mu.RUnlock()

	cc, err := countryCode(country)
	if err != nil {
		return nil, err
	}
	req, err := s.buildRequest(ctx, tmpl, cookies, country, cc, max)
	if err != nil {
		return nil, err
	}
	resp, err := s.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("search transport: %w", err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("search read body: %w", err)
	}
	switch resp.StatusCode {
	case http.StatusOK:
		// fall through
	case http.StatusUnauthorized, http.StatusForbidden:
		return nil, fmt.Errorf("%w: status %d %s", ErrAuthFailed, resp.StatusCode, snippet(body))
	case http.StatusNotFound:
		// Observed behaviour in production: X returns 404 (empty body)
		// for some otherwise-valid GraphQL searches — notably
		// `place_country:EG` always 404s while `place_country:SA`
		// returns a real timeline with the identical cookie jar +
		// transaction id. Treating 404 as auth failure flooded the
		// log and triggered useless CDP refreshes. Read it as
		// "no results for this query" instead.
		return nil, nil
	default:
		return nil, fmt.Errorf("search status %d: %s", resp.StatusCode, snippet(body))
	}
	return parseTimeline(body, country)
}

func (s *HTTPScraper) buildRequest(
	ctx context.Context,
	tmpl SearchTemplate,
	cookies Cookies,
	country server.Country,
	countryCode string,
	max int,
) (*http.Request, error) {
	// Reuse the captured features blob verbatim. Variables we author —
	// rawQuery + count + product (Latest = chronological). Encoding
	// uses url.QueryEscape (%20 for spaces, matching the browser)
	// rather than url.Values.Encode (which uses + for spaces, which
	// the endpoint rejects).
	tu, err := url.Parse(tmpl.URL)
	if err != nil {
		return nil, fmt.Errorf("template URL parse: %w", err)
	}
	featuresEnc := tu.Query().Get("features")
	if featuresEnc == "" {
		return nil, fmt.Errorf("template missing features param")
	}
	vars := map[string]any{
		"rawQuery":                              fmt.Sprintf("place_country:%s -is:retweet -filter:replies", countryCode),
		"count":                                 max,
		"querySource":                           "typed_query",
		"product":                               "Latest",
		"withGrokTranslatedBio":                 true,
		"withQuickPromoteEligibilityTweetFields": false,
	}
	varsJSON, _ := json.Marshal(vars)

	endpoint := "https://x.com/i/api/graphql/" + tmpl.QueryID + "/SearchTimeline"
	full := endpoint +
		"?variables=" + url.QueryEscape(string(varsJSON)) +
		"&features=" + url.QueryEscape(featuresEnc)

	req, err := http.NewRequestWithContext(ctx, "GET", full, nil)
	if err != nil {
		return nil, err
	}
	// Apply every browser-captured header (User-Agent, sec-ch-ua-*,
	// x-twitter-*, AND the critical x-client-transaction-id). We
	// rewrite a few that need our own values.
	for k, v := range tmpl.Headers {
		req.Header.Set(k, v)
	}
	req.Header.Set("Authorization", "Bearer "+xBearer)
	req.Header.Set("Cookie", cookies.CookieHeader())
	req.Header.Set("x-csrf-token", cookies.CT0)
	req.Header.Set("Accept", "*/*")
	// Referer is what the JS would set for a typed search of this
	// country (no leak of personal browsing history).
	req.Header.Set("Referer", "https://x.com/search?q=place_country%3A"+countryCode+"&src=typed_query")
	_ = strconv.Itoa // keep the import live if we need it later
	_ = country       // currently only used for query — kept for future per-country headers
	return req, nil
}

func countryCode(c server.Country) (string, error) {
	switch c {
	case server.CountryKSA:
		return "SA", nil
	case server.CountryEgypt:
		return "EG", nil
	default:
		return "", fmt.Errorf("unsupported country %q", c)
	}
}

func snippet(b []byte) string {
	s := string(b)
	if len(s) > 240 {
		s = s[:240] + "…"
	}
	return strings.TrimSpace(s)
}
