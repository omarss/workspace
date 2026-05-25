package scrape

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/omarss/workspace/tweets/internal/server"
)

// parseTimeline walks the GraphQL SearchTimeline response and pulls
// out the tweet nodes. X's response is a deeply-nested
// instructions/entries tree where each entry contains a `content`
// field that eventually houses a `tweet_results.result` whose
// `__typename` is either `Tweet` or `TweetWithVisibilityResults`
// (the latter wraps the former in a visibility-policy envelope).
//
// Rather than hardcode the path (which has changed across X
// revisions), this walks recursively for any node with one of those
// __typenames and pulls fields off the discovered `legacy` + `core`
// children. Resilient to schema drift.
func parseTimeline(body []byte, country server.Country) ([]server.Tweet, error) {
	var raw map[string]any
	if err := json.Unmarshal(body, &raw); err != nil {
		return nil, fmt.Errorf("decode timeline: %w", err)
	}
	// Reject error-shaped bodies early so callers see the underlying
	// X complaint rather than an empty result.
	if errs, ok := raw["errors"].([]any); ok && len(errs) > 0 {
		return nil, fmt.Errorf("timeline errors: %v", errs)
	}

	seen := make(map[string]struct{})
	var out []server.Tweet
	walk(raw, func(m map[string]any) {
		t, ok := extractTweet(m, country)
		if !ok {
			return
		}
		if _, dup := seen[t.ID]; dup {
			return
		}
		seen[t.ID] = struct{}{}
		out = append(out, t)
	})
	return out, nil
}

func walk(v any, visit func(map[string]any)) {
	switch x := v.(type) {
	case map[string]any:
		visit(x)
		for _, vv := range x {
			walk(vv, visit)
		}
	case []any:
		for _, vv := range x {
			walk(vv, visit)
		}
	}
}

func extractTweet(m map[string]any, country server.Country) (server.Tweet, bool) {
	typ, _ := m["__typename"].(string)
	if typ != "Tweet" && typ != "TweetWithVisibilityResults" {
		return server.Tweet{}, false
	}
	core := m
	if typ == "TweetWithVisibilityResults" {
		// Drill into the wrapped tweet.
		if inner, ok := m["tweet"].(map[string]any); ok {
			core = inner
		}
	}
	id, _ := core["rest_id"].(string)
	if id == "" {
		return server.Tweet{}, false
	}
	legacy, _ := core["legacy"].(map[string]any)
	if legacy == nil {
		return server.Tweet{}, false
	}
	text, _ := legacy["full_text"].(string)
	if text == "" {
		return server.Tweet{}, false
	}
	createdAt, _ := legacy["created_at"].(string)
	ts, err := time.Parse(time.RubyDate, createdAt)
	if err != nil {
		// X uses Ruby date format ("Mon Jan 02 15:04:05 -0700 2006").
		// On parse failure, fall back to now() rather than dropping the
		// tweet — UI just shows the wrong relative time momentarily.
		ts = time.Now().UTC()
	}

	out := server.Tweet{
		ID:           id,
		Text:         text,
		CreatedAt:    ts.UTC(),
		Country:      country,
		ReplyCount:   intField(legacy, "reply_count"),
		LikeCount:    intField(legacy, "favorite_count"),
		RetweetCount: intField(legacy, "retweet_count"),
	}
	if lang, ok := legacy["lang"].(string); ok {
		out.Lang = lang
	}
	if place, ok := legacy["place"].(map[string]any); ok {
		if fn, _ := place["full_name"].(string); fn != "" {
			out.Place = fn
		}
	}

	// Author info lives under core.user_results.result.legacy.{name,screen_name}.
	// Author info path. X moved {name, screen_name} from the user's
	// legacy block up into a sibling `core` block in mid-2026:
	//   tweet.core.user_results.result.core.{name, screen_name}
	// The legacy path still exists for some account types (suspended,
	// quoted, etc.), so try the new path first and fall back to the
	// old one. Both staying empty just leaves the handle blank — the
	// UI tolerates it.
	if c, ok := core["core"].(map[string]any); ok {
		if ur, ok := c["user_results"].(map[string]any); ok {
			if r, ok := ur["result"].(map[string]any); ok {
				if uc, ok := r["core"].(map[string]any); ok {
					out.Author, _ = uc["name"].(string)
					out.Handle, _ = uc["screen_name"].(string)
				}
				if out.Author == "" || out.Handle == "" {
					if l, ok := r["legacy"].(map[string]any); ok {
						if n, _ := l["name"].(string); n != "" && out.Author == "" {
							out.Author = n
						}
						if sn, _ := l["screen_name"].(string); sn != "" && out.Handle == "" {
							out.Handle = sn
						}
					}
				}
			}
		}
	}
	return out, true
}

func intField(m map[string]any, key string) int {
	if n, ok := m[key].(float64); ok {
		return int(n)
	}
	return 0
}
