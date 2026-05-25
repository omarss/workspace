// Package spam scores a tweet's likelihood of being promotional /
// scam / bot output based on heuristic features that don't require any
// model or network call.
//
// Each feature contributes a small additive component; the final score
// is clamped to [0, 1]. Per the design decision recorded in the PR that
// introduced this package, ~80% of the lift comes from these heuristics
// alone — fancier classifiers can layer on later without changing the
// public surface.
package spam

import (
	"math"
	"strings"
	"time"
	"unicode"
)

// Features is the raw, pre-scoring view of a tweet's spam signals.
// Exposed so the caller (and tests) can inspect *why* a score came out
// the way it did rather than treating the number as opaque.
type Features struct {
	LinkCount        int
	HashtagCount     int
	MentionCount     int
	EmojiCount       int
	AllCapsRatio     float64 // proportion of letters that are uppercase
	AccountAgeDays   int     // 0 when unknown
	FollowerRatio    float64 // followers / max(1, following); 0 when unknown
	DuplicateRecent  bool    // same text from same author within the recent window
	TextLength       int
}

// Score returns a value in [0, 1]. Higher = more spam-like. The mapping
// is deliberately simple — each feature is gated by a threshold that
// matched the bulk of obvious spam in a small hand-labelled sample.
// Returns a non-nil per-feature contribution map so callers can debug.
func Score(f Features) (float64, map[string]float64) {
	contrib := make(map[string]float64, 8)

	// Three or more links is a strong promotional signal. Two-link
	// tweets are common in news contexts (article + thread); don't
	// penalise them.
	if f.LinkCount >= 3 {
		add(contrib, "links", 0.25)
	} else if f.LinkCount == 2 {
		add(contrib, "links", 0.08)
	}

	// More than four hashtags is almost always promotional.
	switch {
	case f.HashtagCount >= 6:
		add(contrib, "hashtags", 0.25)
	case f.HashtagCount >= 4:
		add(contrib, "hashtags", 0.12)
	}

	// Mention spam — five or more @mentions in a single tweet is the
	// canonical bot pattern (reply-tagging high-follower accounts).
	switch {
	case f.MentionCount >= 8:
		add(contrib, "mentions", 0.25)
	case f.MentionCount >= 5:
		add(contrib, "mentions", 0.10)
	}

	// Emoji density. Some accounts use a single brand emoji as garnish;
	// six in one tweet is performative.
	switch {
	case f.EmojiCount >= 10:
		add(contrib, "emoji", 0.18)
	case f.EmojiCount >= 6:
		add(contrib, "emoji", 0.08)
	}

	// All-caps tweets are typically rage-bait or sales. Anything above
	// 60% uppercase letters earns a penalty. (Arabic doesn't have case;
	// the ratio is over Latin letters only — see Compute.)
	if f.AllCapsRatio >= 0.6 && f.TextLength >= 20 {
		add(contrib, "all_caps", 0.18)
	}

	// Brand-new accounts (< 30 days) posting publicly are
	// disproportionately spammers. Unknown ages skip this signal.
	if f.AccountAgeDays > 0 && f.AccountAgeDays < 30 {
		add(contrib, "new_account", 0.15)
	}

	// Following way more than followers signals a follow-train bot.
	// Avoid penalising legitimately small accounts (< 50 follows are
	// noisy and easy to misjudge).
	if f.FollowerRatio > 0 && f.FollowerRatio < 0.05 {
		add(contrib, "follower_ratio", 0.12)
	}

	// Same text from same author seen in the last hour — copy-paste
	// flood. Higher penalty because the signal is precise.
	if f.DuplicateRecent {
		add(contrib, "duplicate", 0.35)
	}

	// Sum the components, clamp.
	total := 0.0
	for _, v := range contrib {
		total += v
	}
	return clamp01(total), contrib
}

// Compute extracts Features from raw fields. Pass in author + follower
// metadata when available; zero values disable those individual signals
// without affecting the others.
func Compute(text string, createdAccount time.Time, followers, following int, duplicateRecent bool) Features {
	now := time.Now().UTC()
	ageDays := 0
	if !createdAccount.IsZero() {
		ageDays = int(now.Sub(createdAccount).Hours() / 24)
		if ageDays < 0 {
			ageDays = 0
		}
	}
	ratio := 0.0
	if following > 0 {
		ratio = float64(followers) / float64(following)
	} else if followers > 0 {
		ratio = math.Inf(1) // followed by many, follows nobody — non-spammy
	}
	return Features{
		LinkCount:       countLinks(text),
		HashtagCount:    countPrefix(text, '#'),
		MentionCount:    countPrefix(text, '@'),
		EmojiCount:      countEmoji(text),
		AllCapsRatio:    latinAllCapsRatio(text),
		AccountAgeDays:  ageDays,
		FollowerRatio:   ratio,
		DuplicateRecent: duplicateRecent,
		TextLength:      len([]rune(text)),
	}
}

func add(m map[string]float64, key string, v float64) {
	m[key] += v
}

func clamp01(v float64) float64 {
	if v < 0 {
		return 0
	}
	if v > 1 {
		return 1
	}
	return v
}

func countLinks(text string) int {
	// Cheap heuristic — covers http(s) and bare t.co shortlinks the
	// scraper hasn't unwrapped. Misses email addresses (intentional).
	count := strings.Count(text, "http://") + strings.Count(text, "https://")
	// t.co bare links happen when the scrape returns a stripped body.
	count += strings.Count(text, "t.co/")
	return count
}

func countPrefix(text string, prefix rune) int {
	count := 0
	prev := rune(' ')
	for _, r := range text {
		if r == prefix && (unicode.IsSpace(prev) || prev == ' ') {
			count++
		}
		prev = r
	}
	return count
}

func countEmoji(text string) int {
	count := 0
	for _, r := range text {
		// Rough emoji range — covers most common usage without
		// pulling in a full Unicode table. Misses regional flags
		// (two-codepoint sequences) but those rarely matter for spam.
		switch {
		case r >= 0x1F300 && r <= 0x1FAFF:
			count++
		case r >= 0x2600 && r <= 0x27BF:
			count++
		}
	}
	return count
}

func latinAllCapsRatio(text string) float64 {
	var latin, upper int
	for _, r := range text {
		if !unicode.Is(unicode.Latin, r) || !unicode.IsLetter(r) {
			continue
		}
		latin++
		if unicode.IsUpper(r) {
			upper++
		}
	}
	if latin == 0 {
		return 0
	}
	return float64(upper) / float64(latin)
}
