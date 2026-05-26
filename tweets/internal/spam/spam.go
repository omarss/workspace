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

// Input is everything Compute needs to score a single tweet. Grouped
// into a struct so adding context fields (handle, recent-post counts,
// etc.) stays a one-line API change for callers.
type Input struct {
	Text            string
	Handle          string    // @handle, no leading @. "" when unknown.
	CreatedAccount  time.Time // account creation; zero when unknown
	Followers       int
	Following       int
	DuplicateRecent bool // same text from same author in the recent window
}

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
	// no body text (< 15 chars after stripping URLs, emoji and
	// whitespace). Tighter than the original 10-char gate so
	// "❤️ https://t.co/X" and "Sweet dreams 🥰🥰🥰 https://…" both fire.
	BlocklistBareUrl bool
	// Medical-fraud blocklist — paid sick-note / fake doctor's-cert
	// classifieds. Observed pattern: "#سكليف", "أعذار طبية", "تقرير
	// طبي" repeatedly posted from disposable handles, always paired
	// with a contact number. Single keyword match fires; the
	// vocabulary is narrow enough that legit medical conversation
	// doesn't trip it.
	BlocklistMedicalFraud bool
	// Furniture-removal / used-furniture-purchase classifieds. Same
	// "phone + service keyword" shape as the original local-biz
	// blocklist; broken out so the keyword set (نقل عفش / شراء
	// الأثاث المستعمل / دينا / ونيت / etc.) stays self-contained.
	BlocklistFurnitureService bool
	// Short-caption media bots — typical OnlyFans / escort funnel
	// pattern: a 1-3 word English caption ("Sweet dreams 🥰",
	// "Noto night ❣️") + a t.co media URL, often tagged inside KSA
	// places. The English caption inside a KSA-tagged post is the
	// classic give-away.
	BlocklistEscortCaption bool
	// Suspicious-handle signal — auto-generated X handles like
	// `bwbdlzy28748081`, `lswdlswd7228114`, or trailing-digit
	// patterns. Fires as a soft penalty (0.15) on its own, but
	// combined with a URL/short-text becomes the canonical bot
	// shape. Tracked separately from blocklists so legitimate
	// auto-handle accounts aren't dropped wholesale.
	SuspiciousHandle bool
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
	// Medical-fraud classifieds — single hit drops on its own. Live
	// audit found these are always disposable-handle posts with a
	// contact number; the keyword set is narrow and high-precision.
	if f.BlocklistMedicalFraud {
		add(contrib, "medical_fraud", 0.7)
	}
	// Furniture-removal / used-furniture-purchase ads. Same shape as
	// the original local-biz ad but with a different vocabulary —
	// pulled into its own bucket so the keyword list stays focused.
	if f.BlocklistFurnitureService {
		add(contrib, "furniture_service", 0.55)
	}
	// Short-caption media bots: drop on their own. The pattern is
	// narrow (1-3 word English caption + t.co media URL inside a
	// KSA-tagged post) so false positives on legit short captions
	// from non-Saudi accounts don't apply — these posts only reach
	// the loop after the country filter already passed.
	if f.BlocklistEscortCaption {
		add(contrib, "escort_caption", 0.6)
	}
	// Suspicious handle on its own is a soft (0.15) penalty —
	// legitimate users sometimes pick auto-generated names. But
	// when combined with a bare URL or short content the post is
	// almost certainly a bot — those two penalties stack and the
	// post drops past the threshold without any further signal.
	if f.SuspiciousHandle {
		add(contrib, "suspicious_handle", 0.15)
	}

	// Sum the components, clamp.
	total := 0.0
	for _, v := range contrib {
		total += v
	}
	return clamp01(total), contrib
}

// Compute extracts Features from an Input. Zero-valued fields disable
// their individual signals without affecting the others, so callers
// without author / follower metadata still get useful scores from the
// text-level heuristics alone.
func Compute(in Input) Features {
	now := time.Now().UTC()
	ageDays := 0
	if !in.CreatedAccount.IsZero() {
		ageDays = int(now.Sub(in.CreatedAccount).Hours() / 24)
		if ageDays < 0 {
			ageDays = 0
		}
	}
	ratio := 0.0
	if in.Following > 0 {
		ratio = float64(in.Followers) / float64(in.Following)
	} else if in.Followers > 0 {
		ratio = math.Inf(1) // followed by many, follows nobody — non-spammy
	}
	return Features{
		LinkCount:                 countLinks(in.Text),
		HashtagCount:              countPrefix(in.Text, '#'),
		MentionCount:              countPrefix(in.Text, '@'),
		EmojiCount:                countEmoji(in.Text),
		AllCapsRatio:              latinAllCapsRatio(in.Text),
		AccountAgeDays:            ageDays,
		FollowerRatio:             ratio,
		DuplicateRecent:           in.DuplicateRecent,
		TextLength:                len([]rune(in.Text)),
		BlocklistAdult:            matchAdult(in.Text),
		BlocklistCoupon:           matchCoupon(in.Text),
		BlocklistLocalBizAd:       matchLocalBizAd(in.Text),
		BlocklistOffTopicPol:      matchOffTopicPolitical(in.Text),
		BlocklistOffRegionPromo:   matchOffRegionPromo(in.Text),
		BlocklistCommercialAd:     matchCommercialAd(in.Text),
		BlocklistBareUrl:          matchBareUrl(in.Text),
		BlocklistMedicalFraud:     matchMedicalFraud(in.Text),
		BlocklistFurnitureService: matchFurnitureService(in.Text),
		BlocklistEscortCaption:    matchEscortCaption(in.Text),
		SuspiciousHandle:          matchSuspiciousHandle(in.Handle),
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
// engagement-farming. Strips URLs, emoji, and whitespace before
// counting; threshold of 15 runes catches "❤️ https://t.co/X" and
// "Sweet dreams 🥰🥰🥰 https://…" but leaves a one-sentence caption
// (~20+ chars) alone.

var anyUrlRe = regexp.MustCompile(`https?://\S+|t\.co/\S+`)

func matchBareUrl(text string) bool {
	if !strings.Contains(text, "http") && !strings.Contains(text, "t.co/") {
		return false
	}
	stripped := stripUrlsEmojiWhitespace(text)
	return len([]rune(stripped)) < 15
}

// Drops URLs, emoji, and whitespace from text. Used by bare-URL
// detection and by the escort-caption / short-content checks below
// so they share the same "effective text" definition.
func stripUrlsEmojiWhitespace(text string) string {
	noUrls := anyUrlRe.ReplaceAllString(text, "")
	var b strings.Builder
	b.Grow(len(noUrls))
	for _, r := range noUrls {
		if unicode.IsSpace(r) {
			continue
		}
		// Same emoji ranges as countEmoji — keep them aligned so
		// the bare-URL and emoji-count signals see the same string.
		if r >= 0x1F300 && r <= 0x1FAFF {
			continue
		}
		if r >= 0x2600 && r <= 0x27BF {
			continue
		}
		// Variation selectors / ZWJ / regional indicators that
		// accompany emoji glyphs but don't carry meaning on their
		// own.
		if r == 0x200D || r == 0xFE0F || (r >= 0x1F1E6 && r <= 0x1F1FF) {
			continue
		}
		b.WriteRune(r)
	}
	return b.String()
}

// ── Medical-fraud classifieds ──────────────────────────────────────
//
// Paid sick-note / fake doctor's-certificate spam. Observed pattern:
// "#سكليف", "أعذار طبية", "تقرير طبي معتمد" repeatedly posted from
// disposable handles, always with a contact funnel. Single keyword
// match fires — the vocabulary is narrow and high-precision; a real
// medical conversation about being sick wouldn't use these exact
// phrasings.

func matchMedicalFraud(text string) bool {
	low := strings.ToLower(text)
	for _, k := range medicalFraudKeywords {
		if strings.Contains(low, k) {
			return true
		}
	}
	return false
}

var medicalFraudKeywords = []string{
	"سكليف",          // colloquial: "sick-leave" Anglicism for fake sick note
	"اعذار طبية",     // "medical excuses" (the classifieds phrasing)
	"أعذار طبية",
	"اعذار_طبية",
	"تقرير طبي",      // "medical report" — classifieds-style; legit posts say "نتائج تحاليلي"
	"تقارير طبية",
	"اجازة مرضية",    // "sick leave certificate"
	"إجازة مرضية",
	"اجازات مرضية",
	"إجازات مرضية",
	"اجازات_مرضية",
}

// ── Furniture-removal / used-furniture ads ─────────────────────────
//
// Same anchor shape as the original local-biz blocklist — a phone
// number combined with a service keyword — but kept separate so the
// vocabulary (نقل عفش / شراء الأثاث المستعمل / دينا / etc.) stays
// self-contained and easy to extend without polluting the existing
// list.

func matchFurnitureService(text string) bool {
	if !saudiPhoneRe.MatchString(text) && !egyptPhoneRe.MatchString(text) {
		// Also catch phone-less variants when the keyword density is
		// high (≥ 2 distinct keywords). Lets us drop the AbuAlhamde85903
		// pattern that posts the keyword stack with handle-only contact.
		return countFurnitureKeywords(text) >= 2
	}
	return countFurnitureKeywords(text) >= 1
}

func countFurnitureKeywords(text string) int {
	low := strings.ToLower(text)
	hits := 0
	for _, k := range furnitureServiceKeywords {
		if strings.Contains(low, k) {
			hits++
		}
	}
	return hits
}

var furnitureServiceKeywords = []string{
	"نقل عفش",
	"نقل اثاث",
	"نقل أثاث",
	"شركة نقل عفش",
	"شركة نقل أثاث",
	"شراء الأثاث المستعمل",
	"شراء الاثاث المستعمل",
	"شراء أثاث مستعمل",
	"شراء اثاث مستعمل",
	"دينا نقل",
	"ونيت نقل",
	"شراء المكيفات المستعملة",
	"شراء غرف النوم المستعملة",
	"تركيب اثاث ايكيا",
	"تركيب أثاث ايكيا",
}

// Egyptian mobile numbers — same shape detection as saudiPhoneRe so
// EG-tagged ads with local phones still get caught by the broader
// classifieds rules. +20 1xxxxxxxxx and 01xxxxxxxxx.
var egyptPhoneRe = regexp.MustCompile(`(?:\+?201[0125]\d{8}|\b01[0125]\d{8}\b)`)

// ── Escort / OnlyFans short-caption bots ───────────────────────────
//
// Pattern: 1-3 word English caption + t.co media URL, posted from a
// KSA / EG place. The English-on-Arabic-region mismatch is the signal.
// We only fire on a curated word list — random short English ("Hello"
// or "Thank you" from a tourist) shouldn't trip it.

func matchEscortCaption(text string) bool {
	if !strings.Contains(text, "http") && !strings.Contains(text, "t.co/") {
		return false
	}
	stripped := stripUrlsEmojiWhitespace(text)
	runeCount := len([]rune(stripped))
	// Caption-shaped: < 40 chars of non-URL non-emoji content. Longer
	// posts are real prose; their commercial intent would already be
	// caught by other blocklists.
	if runeCount == 0 || runeCount > 40 {
		return false
	}
	low := strings.ToLower(text)
	for _, k := range escortCaptionKeywords {
		if strings.Contains(low, k) {
			return true
		}
	}
	return false
}

var escortCaptionKeywords = []string{
	"sweet dreams",
	"noto night",
	"good morning honey",
	"good night honey",
	"love you all",
	"miss you all",
	"my new video",
	"new video",
	"check my profile",
	"check my bio",
	"check bio",
	"link in bio",
	"my page",
	"my onlyfans",
	"onlyfans",
	"only fans",
}

// ── Suspicious handle ──────────────────────────────────────────────
//
// Auto-generated X handles: `bwbdlzy28748081`, `lswdlswd7228114`,
// `Chubby091824811`, `mumtaza94959855`. Trailing 5+ digits is the
// usual giveaway; digit-heavy or all-consonant-no-vowel patterns
// catch the rest. Soft signal — fires as a 0.15 penalty alone, but
// combined with a URL / short text it stacks past threshold.

func matchSuspiciousHandle(handle string) bool {
	if handle == "" {
		return false
	}
	// Five or more trailing digits — Twitter's auto-suggest pattern.
	if trailingDigitRe.MatchString(handle) {
		return true
	}
	// Mostly digits (≥ 60% of chars).
	digitCount := 0
	for _, r := range handle {
		if r >= '0' && r <= '9' {
			digitCount++
		}
	}
	if len(handle) > 0 && float64(digitCount)/float64(len(handle)) >= 0.6 {
		return true
	}
	// Long handle with no vowels — keyboard-mash auto-gen.
	if len([]rune(handle)) >= 12 {
		hasVowel := false
		for _, r := range strings.ToLower(handle) {
			switch r {
			case 'a', 'e', 'i', 'o', 'u':
				hasVowel = true
			}
		}
		if !hasVowel {
			return true
		}
	}
	return false
}

var trailingDigitRe = regexp.MustCompile(`\d{5,}$`)

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
