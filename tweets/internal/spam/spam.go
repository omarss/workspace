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
	// Commercial advertisements — product / service / course /
	// educational promo. Distinct from BlocklistLocalBizAd (which
	// targets repetitive Saudi-phone-anchored classifieds) in that
	// it catches WhatsApp / product-page / price-statement /
	// course-registration shapes. Triggered by any of several strong
	// commercial signals; see matchCommercialAd() for the full set.
	BlocklistCommercialAd bool
	// Bare-URL bot posts: a single t.co / https link with essentially
	// no body text (< 10 chars after stripping URLs). These are
	// usually image / video cross-posts that carry no information
	// once the link target is dead, plus a chunk of low-effort
	// engagement-farming bot traffic.
	BlocklistBareUrl bool
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
		// 0.55 (was 0.4) so a single match drops the tweet on its own.
		// matchOffTopicPolitical already requires 2 distinct keywords
		// out of a narrow curated set, so a single match is itself the
		// 2-keyword combo we wanted to catch — bumping the weight
		// finishes the job instead of relying on coincident link /
		// emoji penalties that the leak case ("Show respect and bow!
		// ... Custodian of the Two Holy Mosques ...") doesn't have.
		add(contrib, "off_topic_political", 0.55)
	}
	if f.BlocklistOffRegionPromo {
		add(contrib, "off_region_promo", 0.55)
	}
	// Strong enough to drop on its own — every match site is a
	// deliberate ad signal (price statement, product URL, WhatsApp +
	// CTA, course-with-payment, etc.).
	if f.BlocklistCommercialAd {
		add(contrib, "commercial_ad", 0.55)
	}
	// Bare-URL posts are mostly low-effort cross-posts; weight them
	// just below threshold so a single other signal (link spam,
	// emoji spam, etc.) pushes them over. Avoids dropping every
	// short-comment-plus-link tweet outright.
	if f.BlocklistBareUrl {
		add(contrib, "bare_url", 0.4)
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
		BlocklistCommercialAd:   matchCommercialAd(text),
		BlocklistBareUrl:        matchBareUrl(text),
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

// ── Commercial ads ─────────────────────────────────────────────────
//
// Catches paid promotion regardless of subject — product ads, course
// signups, "buy/order/register now" pitches, WhatsApp-anchored sales
// flows. The signal is the *commercial intent* (price + call-to-action,
// product-page URL, contact-funnel) rather than the subject; that's
// why "educational" promos (paid courses, bootcamps, certifications)
// land here too — same shape, same ad.
//
// A single match fires the blocklist. Each pattern is narrow enough
// that the false-positive case (a non-promotional tweet using the
// same exact phrasing) is rare. The pattern set:
//
//   1. Saudi phone number + WhatsApp link.
//   2. Phone number + an explicit CTA verb.
//   3. Explicit price-inclusive phrasing ("السعر شامل", etc.).
//   4. Product-page URL shape (`/p\d{7,}` in the path — used by
//      Salla, Zid, JollyChic, Shein, etc.).
//   5. WhatsApp-business shortlink (wa.me / api.whatsapp.com/send).
//   6. Course / certificate signup phrasing.
//   7. "Now available" + a price digit.

var saudiPhoneAdRe = regexp.MustCompile(`(?:\+?9665\d{8}|\b05\d{8}\b)`)
var productUrlRe = regexp.MustCompile(`/p\d{7,}\b`)
var pricePhraseRe = regexp.MustCompile(`\d+\s*(?:ريال|sar|ر\.س|aed|درهم|ج\.م|جنيه)`)

func matchCommercialAd(text string) bool {
	low := strings.ToLower(text)
	hasPhone := saudiPhoneAdRe.MatchString(text)
	// Accept the Arabic word "واتساب" / "الواتساب" too — beauty-clinic
	// and similar ads write "تواصل عبر الواتساب" instead of dropping
	// the wa.me URL. The phrase paired with a phone or CTA is the same
	// commercial funnel shape regardless of whether the URL appears.
	hasWhatsApp := strings.Contains(low, "wa.me") ||
		strings.Contains(low, "whatsapp.com/send") ||
		strings.Contains(low, "api.whatsapp.com") ||
		strings.Contains(text, "واتساب")
	hasProductUrl := productUrlRe.MatchString(text)
	hasPrice := pricePhraseRe.MatchString(low)

	if hasPhone && hasWhatsApp {
		return true
	}
	if hasProductUrl {
		return true
	}
	// WhatsApp is itself a commercial-funnel signal, so any CTA (even
	// the soft "contact" verb) is enough alongside it.
	if hasWhatsApp && (containsAny(low, commercialCtaKeywords) ||
		containsAny(low, contactCtaKeywords)) {
		return true
	}
	// Phone alone is NOT enough — many legit "call us at X for
	// inquiries" messages mention تواصل. Require a strictly commercial
	// CTA (buy / order / book / subscribe) so customer-service phone
	// announcements don't trip the rule.
	if hasPhone && containsAny(low, commercialCtaKeywords) {
		return true
	}
	if containsAny(low, strongAdPhrases) {
		return true
	}
	if containsAny(low, courseAdPhrases) {
		return true
	}
	// Price phrase is commercial on its own when paired with any CTA
	// (including the softer "contact" verb — a price + "contact us"
	// is the textbook ad shape).
	if hasPrice && (containsAny(low, commercialCtaKeywords) ||
		containsAny(low, contactCtaKeywords)) {
		return true
	}
	return false
}

func containsAny(text string, needles []string) bool {
	for _, n := range needles {
		if strings.Contains(text, n) {
			return true
		}
	}
	return false
}

// commercialCtaKeywords are unambiguously purchase-intent verbs:
// buy / order / book / subscribe. Pairing any of these with a phone
// number, a price, or a WhatsApp link is enough to call the post an ad.
var commercialCtaKeywords = []string{
	"اشتري", "اشتروا", "للشراء",
	"اطلب", "اطلبوا",
	"احجز", "احجزوا", "احجزي", "للحجز",
	"اشترك", "اشتركوا",
	"buy now", "order now", "shop now",
	"book now", "subscribe", "sign up",
}

// contactCtaKeywords are the softer "contact us" verb family. تواصل
// is heavily used in legitimate customer-service announcements
// ("المتجر مغلق اليوم، يمكنكم التواصل على 055…"), so we DON'T treat
// phone-plus-contact as an ad — only when paired with a stronger
// commercial signal (WhatsApp link, explicit price phrase).
var contactCtaKeywords = []string{
	"تواصل", "تواصلوا", "للتواصل",
}

var strongAdPhrases = []string{
	"متوفر الآن", "متوفر الان",
	"السعر شامل", "السعر يشمل", "شامل الضريبة",
	"للحجز عبر", "للطلب عبر", "للتواصل واتساب",
	"للطلب واتساب", "للحجز واتساب",
	"خصم خاص", "خصم لفترة محدودة",
	"limited time offer",
}

var courseAdPhrases = []string{
	"احصل على شهادة", "احصلي على شهادة",
	"اشترك بدورة", "اشترك بالدورة", "اشتركوا بالدورة",
	"دورة تدريبية معتمدة",
	"بوت كامب",
	"شهادة معتمدة",
	"online course", "bootcamp",
	"certified course",
	"masterclass",
	"enroll now",
}

// ── Bare-URL bots ──────────────────────────────────────────────────
//
// Identifies low-effort posts that consist of a URL plus essentially no
// other content — typical bot media reposts, X-CDN'd image dumps,
// engagement-farming. Threshold of 10 runes leaves room for a leading
// emoji or two-word caption while catching the bare https://t.co/… case.

var anyUrlRe = regexp.MustCompile(`https?://\S+|t\.co/\S+`)

func matchBareUrl(text string) bool {
	if !strings.Contains(text, "http") && !strings.Contains(text, "t.co/") {
		return false
	}
	stripped := anyUrlRe.ReplaceAllString(text, "")
	stripped = strings.TrimSpace(stripped)
	return len([]rune(stripped)) < 10
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
	// Bare t.co/ shortlinks (scraper returned a stripped body). Skip
	// occurrences that are part of a full `https://t.co/...` URL we
	// already counted — otherwise a single shortlink gets counted twice.
	for i := 0; i < len(text); {
		rel := strings.Index(text[i:], "t.co/")
		if rel < 0 {
			break
		}
		at := i + rel
		if at < 3 || text[at-3:at] != "://" {
			count++
		}
		i = at + len("t.co/")
	}
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
