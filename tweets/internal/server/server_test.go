package server

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func newTestServer() http.Handler {
	return New(NewFixtureSource(), nil).Routes()
}

func TestHealthz(t *testing.T) {
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	newTestServer().ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}
	var body HealthResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.Status != "ok" {
		t.Errorf("expected status=ok, got %q", body.Status)
	}
}

func TestTweets_DefaultCountry(t *testing.T) {
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/tweets", nil)
	newTestServer().ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}
	var body FeedResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Countries) != 1 || body.Countries[0] != CountryKSA {
		t.Errorf("expected default country [ksa], got %v", body.Countries)
	}
	if len(body.Tweets) == 0 {
		t.Error("expected fixture tweets, got none")
	}
}

func TestTweets_Egypt(t *testing.T) {
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/tweets?country=eg", nil)
	newTestServer().ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}
	var body FeedResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Countries) != 1 || body.Countries[0] != CountryEgypt {
		t.Errorf("expected [eg], got %v", body.Countries)
	}
	for _, tw := range body.Tweets {
		if tw.Country != CountryEgypt {
			t.Errorf("tweet %q should be tagged egypt, got %q", tw.ID, tw.Country)
		}
	}
}

func TestTweets_BadCountry(t *testing.T) {
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/tweets?country=zz", nil)
	newTestServer().ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for unknown country, got %d", rr.Code)
	}
}

func TestTweets_KeywordQuery_MatchesBody(t *testing.T) {
	// "أبشر" appears in ksa-1's fixture text. The handler should
	// round-trip the term in body.Query and the fixture must respect it.
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/tweets?q=أبشر", nil)
	newTestServer().ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}
	var body FeedResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.Query != "أبشر" {
		t.Errorf("expected echoed query, got %q", body.Query)
	}
	if len(body.Tweets) == 0 {
		t.Fatalf("expected at least one match for أبشر")
	}
	for _, tw := range body.Tweets {
		if !strings.Contains(tw.Text, "أبشر") {
			t.Errorf("non-matching tweet leaked through filter: %q", tw.Text)
		}
	}
}

func TestTweets_KeywordQuery_AndAcrossTokens(t *testing.T) {
	// Whitespace-separated terms AND. ksa-2 (NEOM all-electric…)
	// matches both "neom" and "electric"; ksa-1 (about أبشر) does not.
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/tweets?q=neom+electric", nil)
	newTestServer().ServeHTTP(rr, req)

	var body FeedResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Tweets) != 1 {
		t.Fatalf("expected exactly one match for both terms, got %d", len(body.Tweets))
	}
	if !strings.Contains(body.Tweets[0].Text, "NEOM") {
		t.Errorf("expected NEOM tweet, got %q", body.Tweets[0].Text)
	}
}

func TestTweets_KeywordQuery_BooleanOr(t *testing.T) {
	// `أبشر OR NEOM` matches both ksa-1 (أبشر) and ksa-2 (NEOM).
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/tweets?q=أبشر+OR+NEOM", nil)
	newTestServer().ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}
	var body FeedResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Tweets) != 2 {
		t.Fatalf("expected both KSA tweets (أبشر OR NEOM), got %d", len(body.Tweets))
	}
}

func TestTweets_KeywordQuery_InvalidExpression(t *testing.T) {
	// Unterminated quote → 400.
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, `/tweets?q=%22unterminated`, nil)
	newTestServer().ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for unterminated quote, got %d", rr.Code)
	}
}

func TestTweets_MagicQuery_MatchesNothingInFixturesOK(t *testing.T) {
	// The fixtures don't include event-shaped content, so magic
	// returns zero tweets but the response itself is 200 with
	// magic=true echoed back. Confirms the magic flag round-trips
	// without breaking the response shape.
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/tweets?magic=1&country=ksa,eg", nil)
	newTestServer().ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}
	var body FeedResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if !body.Magic {
		t.Errorf("expected magic=true in response, got false")
	}
	if body.Query == "" {
		t.Error("expected echoed magic query string, got empty")
	}
}

func TestTweets_KeywordQuery_StripsWildcards(t *testing.T) {
	// %% and __ must not reach the store — the handler scrubs them.
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/tweets?q=%25%25NEOM%25%25", nil)
	newTestServer().ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 even with wildcard chars, got %d", rr.Code)
	}
	var body FeedResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if strings.Contains(body.Query, "%") {
		t.Errorf("expected %% stripped from echoed query, got %q", body.Query)
	}
}
