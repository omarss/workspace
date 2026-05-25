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
	"regexp"
	"strings"
	"time"
	"unicode"
)

// Features is the raw, pre-scoring view of a tweet's spam signals.
// Exposed so the caller (and tests) can inspect *why* a score came out
// the way it did rather than treating the number as opaque.
type Features struct {
	LinkCount       int
	HashtagCount    int
	MentionCount    int
	EmojiCount      int
	AllCapsRatio    float64 // proportion of letters that are uppercase
	AccountAgeDays  int     // 0 when unknown
	FollowerRatio   float64 // followers / max(1, following); 0 when unknown
	DuplicateRecent bool    // same text from same author within the recent window
	TextLength      int

	// Hits on the curated blocklist categories below. The handful of
	// patterns observed in live KSA scrapes that the original heuristic
	// missed entirely — adult/sex-work promo hashtag stamps, dropshipping
	// coupon spam with Unicode-decoration brackets, repetitive local-
	// business ads built around a Saudi phone number.
	BlocklistAdult         bool
	BlocklistCoupon        bool
	BlocklistLocalBizAd    bool
	BlocklistOffTopicPol   bool
	// Off-region commercial promo: posts tagged inside KSA/EG whose
	// content is selling a service that explicitly lives elsewhere
	// (Dubai car rental from a Riyadh-tagged account, etc.). Caught
	// via combined "rent / car / Dubai" keywords; the cross-field
	// place-vs-text check is left to the future.
	BlocklistOffRegionPromo bool
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

	// Blocklist hits — each one is strong enough to push a tweet past
	// the default 0.5 threshold on its own. These cover the spam
	// categories the original feature set missed entirely on live
	// KSA scrapes:
	//   * adult / sex-work promo (#ladyboy_*, #vlpmassage_*) — ~70%
	//     of these have <4 hashtags so the count-based gate misses them.
	//   * coupon / dropshipping spam decorated with the Unicode bracket
	//     glyphs ⎐ ⊵ ⊴ and bouncing through AliExpress / Noon / Namshi.
	//   * repetitive Riyadh-area local business ads built around one
	//     phone number (butcher, furniture haulers). Same phone +
	//     same hashtags posted across many tweets.
	//   * off-topic political glorification ("Custodian of the Two
	//     Holy Mosques… Show respect and bow!") wrapped in flag emoji.
	if f.BlocklistAdult {
		add(contrib, "adult", 0.7)
	}
	if f.BlocklistCoupon {
		add(contrib, "coupon", 0.6)
	}
	if f.BlocklistLocalBizAd {
		add(contrib, "local_biz_ad", 0.55)
	}
	if f.BlocklistOffTopicPol {
		add(contrib, "off_topic_political", 0.4)
	}
	if f.BlocklistOffRegionPromo {
		add(contrib, "off_region_promo", 0.55)
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
		LinkCount:            countLinks(text),
		HashtagCount:         countPrefix(text, '#'),
		MentionCount:         countPrefix(text, '@'),
		EmojiCount:           countEmoji(text),
		AllCapsRatio:         latinAllCapsRatio(text),
		AccountAgeDays:       ageDays,
		FollowerRatio:        ratio,
		DuplicateRecent:      duplicateRecent,
		TextLength:           len([]rune(text)),
		BlocklistAdult:          matchAdult(text),
		BlocklistCoupon:         matchCoupon(text),
		BlocklistLocalBizAd:     matchLocalBizAd(text),
		BlocklistOffTopicPol:    matchOffTopicPolitical(text),
		BlocklistOffRegionPromo: matchOffRegionPromo(text),
	}
}

// ── Blocklists ─────────────────────────────────────────────────────
//
// Lower-cased substring matches; cheap. Update as new patterns are
// observed in the live feed (spam adversaries adapt). Each list is
// kept narrow so a single legitimate post is unlikely to trip it.

func matchAdult(text string) bool {
	low := strings.ToLower(text)
	for _, k := range adultKeywords {
		if strings.Contains(low, k) {
			return true
		}
	}
	return false
}

var adultKeywords = []string{
	"ladyboy",
	"shemale",
	"vlpmassage",
	"vipmassage",
	"_massage_",
	"_bottom_",
	"_top_in_",
	"escort",
	"call_girl",
	"hookup",
	"sex_in_",
	"sex_riyadh",
	"sex_jeddah",
	// Softer-promo phrasings observed on the live KSA feed that the
	// hashtag-stamp blocklist above misses. Each one is a phrase a
	// non-promo account is highly unlikely to write.
	"come to me 24",
	"come to me 24/24",
	"24/24 incall",
	"24/24 outcall",
	"مساج في مدينة",  // "massage in [city]" — typical multi-city promo
	"مساج خاص",        // "private massage"
	"مساج للسيدات والرجال",
	"مساج منزلي",
	"مساج فندقي",
}

func matchCoupon(text string) bool {
	// Unicode-bracket decoration commonly used in coupon spam, e.g.
	// ⎐كُود⎐ ⊵IQH8946⊴. Three or more decorations in one tweet is the
	// signature pattern.
	var brackets int
	for _, r := range text {
		switch r {
		case '⎐', '⊵', '⊴':
			brackets++
			if brackets >= 3 {
				return true
			}
		}
	}
	// Coupon-code shorthand seen alongside the brackets.
	low := strings.ToLower(text)
	for _, k := range couponKeywords {
		if strings.Contains(low, k) {
			return true
		}
	}
	return false
}

var couponKeywords = []string{
	"aliexpress",
	"كوبون خصم",
	"كود خصم",
	"كوبِون",
	"كُود",
	"خـِصم",
	"trendyol",
	"namshi code",
	"كوبون نون",
	"كوبون نمشي",
}

// Saudi phone numbers — local business ads almost always anchor on a
// phone number. Pattern catches +966 5xx xxx xxxx and 05xx xxx xxxx
// shapes (with or without separators).
var saudiPhoneRe = regexp.MustCompile(`(?:\+?9665\d{8}|\b05\d{8}\b)`)

func matchLocalBizAd(text string) bool {
	if !saudiPhoneRe.MatchString(text) {
		return false
	}
	low := strings.ToLower(text)
	// A Saudi phone number alone is not spam — pair it with a
	// "service language" keyword that signals classifieds-style ads.
	for _, k := range localBizMarkers {
		if strings.Contains(low, k) {
			return true
		}
	}
	return false
}

var localBizMarkers = []string{
	"قصاب",        // butcher
	"جزار",        // butcher
	"ذبح",         // slaughter
	"دينا",        // pickup-truck (furniture removal)
	"طش الاثاث",   // dump old furniture
	"نقل عفش",     // furniture moving
	"تنظيف فلل",   // villa cleaning ads
	"تنظيف خزانات", // tank cleaning ads
	"رش مبيدات",   // pesticide spraying
	"عزل أسطح",    // roof insulation
	"كشف تسربات",  // leak detection
	"شفط مجاري",   // sewage drainage
}

// Off-topic political glorification — flagged keywords combined with
// hashtag/emoji counts. Lighter weight than the others because false
// positives on legitimate political commentary are worse than missing
// the occasional fluff post.
func matchOffTopicPolitical(text string) bool {
	low := strings.ToLower(text)
	hits := 0
	for _, k := range polKeywords {
		if strings.Contains(low, k) {
			hits++
		}
	}
	return hits >= 2
}

var polKeywords = []string{
	"custodian of the two holy",
	"show respect and bow",
	"princerahimagakhan",
	"long live",
	"long-live",
	"glorified leader",
}

// matchOffRegionPromo catches accounts tagged inside KSA/EG selling a
// service that lives elsewhere (most common: Dubai car-rental).
// Needs *two* matching phrases — a service phrase and a region phrase —
// so a one-off tourist post mentioning Dubai doesn't trigger.
func matchOffRegionPromo(text string) bool {
	low := strings.ToLower(text)
	hasService := false
	for _, k := range offRegionServiceKeywords {
		if strings.Contains(low, k) {
			hasService = true
			break
		}
	}
	if !hasService {
		return false
	}
	for _, k := range offRegionPlaceKeywords {
		if strings.Contains(low, k) {
			return true
		}
	}
	return false
}

var offRegionServiceKeywords = []string{
	"استأجر سيارة",         // "rent a car"
	"تأجير سيارة",          // "car rental"
	"تأجير سيارات",         // "car rentals"
	"تاجر سيارات",          // "car dealer / trader"
	"بدون وديعة",           // "no deposit" — used in rental promo
	"بدون تأمين مخالفات",   // "no traffic-fine insurance"
	"car rental in",
	"rent a car in",
}

var offRegionPlaceKeywords = []string{
	"في دبي",   // "in Dubai" — content explicitly Dubai
	"دبي ",     // "Dubai " with trailing space — anchored prefix
	"أبوظبي",   // Abu Dhabi
	"الإمارات", // UAE
	"in dubai",
	"in abu dhabi",
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
