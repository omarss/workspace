package spam

import (
	"testing"
	"time"
)

// computeLegacy keeps the positional-args shape the original tests
// were written in. Real callers use Compute(Input{...}) directly; the
// helper exists so adding fields to Input doesn't churn every test.
func computeLegacy(text string, createdAt time.Time, followers, following int, dup bool) Features {
	return Compute(Input{
		Text:            text,
		CreatedAccount:  createdAt,
		Followers:       followers,
		Following:       following,
		DuplicateRecent: dup,
	})
}

func TestScore_Clean(t *testing.T) {
	got, _ := Score(computeLegacy(
		"تنبيه: موجة غبار متوقعة على شرق الرياض بعد الساعة الرابعة عصراً.",
		time.Now().Add(-365*24*time.Hour), 5000, 200, false,
	))
	if got > 0.05 {
		t.Errorf("clean tweet scored too high: %.3f", got)
	}
}

func TestScore_HashtagSpam(t *testing.T) {
	got, breakdown := Score(computeLegacy(
		"Buy now! #crypto #moon #pumpit #100x #freelambo #defi #bullrun",
		time.Time{}, 0, 0, false,
	))
	if got < 0.2 {
		t.Errorf("hashtag-stuffed tweet should score >= 0.2, got %.3f (breakdown=%v)", got, breakdown)
	}
}

func TestScore_LinkSpam(t *testing.T) {
	got, _ := Score(computeLegacy(
		"check this https://a.com https://b.com https://c.com great offer",
		time.Time{}, 0, 0, false,
	))
	if got < 0.2 {
		t.Errorf("3-link tweet should score >= 0.2, got %.3f", got)
	}
}

func TestScore_NewAccountAllCaps(t *testing.T) {
	got, breakdown := Score(computeLegacy(
		"DOUBLE YOUR MONEY OVERNIGHT — LIMITED SLOTS, ACT NOW BEFORE THEY ARE GONE",
		time.Now().Add(-5*24*time.Hour), 12, 8000, false,
	))
	if got < 0.3 {
		t.Errorf("new-account all-caps should score >= 0.3, got %.3f (breakdown=%v)", got, breakdown)
	}
}

func TestScore_DuplicateRecentHeavyPenalty(t *testing.T) {
	got, _ := Score(computeLegacy(
		"Visit my store!", time.Time{}, 0, 0, true,
	))
	if got < 0.3 {
		t.Errorf("duplicate-recent should score >= 0.3 alone, got %.3f", got)
	}
}

func TestScore_ClampedToOne(t *testing.T) {
	got, _ := Score(computeLegacy(
		"BUY NOW BUY NOW #crypto #moon #pumpit #100x #freelambo #defi #bullrun #yolo "+
			"https://a.com https://b.com https://c.com https://d.com @x @y @z @w @v @u @t @s",
		time.Now().Add(-1*24*time.Hour), 5, 9000, true,
	))
	if got != 1.0 {
		t.Errorf("expected score clamped to 1.0, got %.3f", got)
	}
}

func TestCountPrefix_OnlyAtWordStart(t *testing.T) {
	// "#hashtag" counts; "in-hash#tag" does not.
	if got := countPrefix("foo #a #b mid#c", '#'); got != 2 {
		t.Errorf("expected 2 hashtags, got %d", got)
	}
}

func TestScore_AdultBlocklist(t *testing.T) {
	// Verbatim hashtag pattern observed in live KSA feed.
	got, breakdown := Score(computeLegacy(
		"#Jeddah_VlPmassage #Jeddah_Fullbodymassage #ladyboy_saudi #Jeddah_massage_moroccan_bath  https://t.co/x",
		time.Time{}, 0, 0, false,
	))
	if got < 0.7 {
		t.Errorf("adult promo should clear 0.7, got %.3f breakdown=%v", got, breakdown)
	}
}

func TestScore_CouponBracketBlocklist(t *testing.T) {
	// Verbatim coupon-bracket pattern observed in live KSA feed.
	got, breakdown := Score(computeLegacy(
		"⎐كُود⎐⎐ايهرب⎐ايهيرب اهرب ⊵IQH8946⊴",
		time.Time{}, 0, 0, false,
	))
	if got < 0.6 {
		t.Errorf("coupon-bracket should clear 0.6, got %.3f breakdown=%v", got, breakdown)
	}
}

func TestScore_CouponKeywordBlocklist(t *testing.T) {
	// AliExpress / Noon / Namshi coupon-code dropshipping text.
	got, _ := Score(computeLegacy(
		"كوبون خصم لطلبك من aliexpress احصل عليه الآن!",
		time.Time{}, 0, 0, false,
	))
	if got < 0.6 {
		t.Errorf("coupon-keyword should clear 0.6, got %.3f", got)
	}
}

func TestScore_LocalBizAdBlocklist(t *testing.T) {
	// Saudi phone + butcher-service keyword — observed pattern.
	got, _ := Score(computeLegacy(
		"قصاب ماهر بالرياض 0533286100 قصاب شمال الرياض",
		time.Time{}, 0, 0, false,
	))
	if got < 0.55 {
		t.Errorf("local-biz ad should clear 0.55, got %.3f", got)
	}
}

func TestScore_LocalBizAd_PhoneAloneNotSpam(t *testing.T) {
	// Same phone format but no service keyword — legitimate, must not fire.
	got, _ := Score(computeLegacy(
		"المتجر مغلق اليوم، يمكنكم التواصل على 0533286100 للاستفسارات",
		time.Time{}, 0, 0, false,
	))
	if got >= 0.5 {
		t.Errorf("legit phone-bearing message must not fire local-biz blocklist, got %.3f", got)
	}
}

func TestScore_OffTopicPolitical(t *testing.T) {
	// Now expected to clear 0.5 on its own — the 2-keyword combo is
	// the whole signal, no need to combine with other penalties.
	got, _ := Score(computeLegacy(
		"The Custodian of the Two Holy Mosques is great. Show respect and bow! #Saudi 🇸🇦",
		time.Time{}, 0, 0, false,
	))
	if got < 0.5 {
		t.Errorf("off-topic political glorification expected >= 0.5, got %.3f", got)
	}
}

func TestScore_PoliticalSingleKeyword_NotDropped(t *testing.T) {
	// One keyword on its own is legitimate news reporting; must not
	// fire. matchOffTopicPolitical requires 2+ hits.
	got, _ := Score(computeLegacy(
		"The Custodian of the Two Holy Mosques chaired today's cabinet meeting.",
		time.Time{}, 0, 0, false,
	))
	if got >= 0.5 {
		t.Errorf("single political-keyword news quote must not fire, got %.3f", got)
	}
}

func TestScore_AdultSoftPromo(t *testing.T) {
	// Verbatim "Come to me" pattern observed in live feed.
	got, _ := Score(computeLegacy(
		"مساج في مدينة جدة   مساج في مدينة الدمام   Come to me 24/24🦋 💃💃💃 https://t.co/x https://t.co/y",
		time.Time{}, 0, 0, false,
	))
	if got < 0.7 {
		t.Errorf("adult soft-promo expected >= 0.7, got %.3f", got)
	}
}

func TestScore_CommercialAd_WhatsAppPhone(t *testing.T) {
	// Verbatim beauty-clinic ad from live audit.
	got, _ := Score(computeLegacy(
		"متى تظهر نتائج ال facetite®️ يمكنكم التواصل معنا وحجز المواعيد عبر الواتساب: 966534854071+ #تجميل",
		time.Time{}, 0, 0, false,
	))
	if got < 0.55 {
		t.Errorf("commercial-ad (phone+CTA) expected >= 0.55, got %.3f", got)
	}
}

func TestScore_CommercialAd_ProductUrl(t *testing.T) {
	// Verbatim oud-perfume product page from live audit.
	got, _ := Score(computeLegacy(
		"عود كلمنتان طبيعي https://t.co/lWywIp2J7gعود-كلمنتان-طبيعي/p44095010",
		time.Time{}, 0, 0, false,
	))
	if got < 0.55 {
		t.Errorf("commercial-ad (product URL) expected >= 0.55, got %.3f", got)
	}
}

func TestScore_CommercialAd_PriceStatement(t *testing.T) {
	// Verbatim "السعر شامل الضريبة" from live audit.
	got, _ := Score(computeLegacy(
		"متوفر الان السعر شامل الضريبة 220 ريال https://t.co/j24ISpaKV2",
		time.Time{}, 0, 0, false,
	))
	if got < 0.55 {
		t.Errorf("commercial-ad (price phrase) expected >= 0.55, got %.3f", got)
	}
}

func TestScore_CommercialAd_CourseAd(t *testing.T) {
	got, _ := Score(computeLegacy(
		"اشترك بدورة تطوير الأعمال — احصل على شهادة معتمدة",
		time.Time{}, 0, 0, false,
	))
	if got < 0.55 {
		t.Errorf("educational/course ad expected >= 0.55, got %.3f", got)
	}
}

func TestScore_CommercialAd_NotFiredByNormalContent(t *testing.T) {
	// Religious post containing the word اشترك (subscribe) in a non-CTA
	// context — must not fire.
	got, _ := Score(computeLegacy(
		"اللهم اشترك معنا في الدعاء يوم عرفة بالخير لإخواننا الحجاج.",
		time.Time{}, 0, 0, false,
	))
	if got >= 0.55 {
		t.Errorf("religious post must not fire commercial-ad, got %.3f", got)
	}
}

func TestScore_BareUrlBot_Caught(t *testing.T) {
	got, _ := Score(computeLegacy(
		"https://t.co/abc123",
		time.Time{}, 0, 0, false,
	))
	// Bare-URL alone is 0.4 — needs at least one extra signal to drop.
	// The duplicate-recent path is what usually flips this past 0.5,
	// so test that combination too.
	if got < 0.35 || got > 0.45 {
		t.Errorf("bare URL alone expected ~0.4, got %.3f", got)
	}
	withDup, _ := Score(computeLegacy(
		"https://t.co/abc123",
		time.Time{}, 0, 0, true,
	))
	if withDup < 0.5 {
		t.Errorf("bare URL + duplicate expected >= 0.5, got %.3f", withDup)
	}
}

func TestScore_BareUrlBot_NotFiredOnRealCaption(t *testing.T) {
	// Twenty-plus characters of real Arabic content + URL — must NOT
	// fire bare-URL even with the tightened 15-rune threshold. This is
	// the "legit short post with image link" case.
	got, _ := Score(computeLegacy(
		"الحمد لله على نعمة الأمن والإيمان 🤍 https://t.co/upk013KFo2",
		time.Time{}, 0, 0, false,
	))
	if got >= 0.5 {
		t.Errorf("real Arabic caption + URL must not fire bare-URL alone, got %.3f", got)
	}
}

func TestScore_OffRegionDubaiRental(t *testing.T) {
	// Verbatim Dubai car-rental tagged-as-KSA pattern.
	got, _ := Score(computeLegacy(
		"🚗 استأجر سيارة اقتصادية في دبي بأفضل الأسعار 💸 بدون وديعة ✅ بدون تأمين مخالفات ❌",
		time.Time{}, 0, 0, false,
	))
	if got < 0.5 {
		t.Errorf("off-region Dubai rental expected >= 0.5, got %.3f", got)
	}
}

func TestScore_OffRegion_DubaiAloneNotSpam(t *testing.T) {
	// "I'm thinking of visiting Dubai" should not trip the off-region
	// blocklist — needs both a service AND a region phrase.
	got, _ := Score(computeLegacy(
		"أفكر بزيارة دبي قريباً، هل لديكم توصيات؟",
		time.Time{}, 0, 0, false,
	))
	if got >= 0.5 {
		t.Errorf("mere Dubai mention must not fire off-region promo, got %.3f", got)
	}
}

func TestScore_OffRegion_RentalInKsaNotSpam(t *testing.T) {
	// Same service language but no off-region anchor — legitimate KSA
	// rental query. Must not fire.
	got, _ := Score(computeLegacy(
		"أبحث عن تأجير سيارة في الرياض لمدة أسبوع، أي توصيات؟",
		time.Time{}, 0, 0, false,
	))
	if got >= 0.5 {
		t.Errorf("KSA rental query must not fire off-region promo, got %.3f", got)
	}
}

func TestScore_LegitimateContentNotFlagged(t *testing.T) {
	// Spot-check: religious daily-life post should pass with a low score.
	got, _ := Score(computeLegacy(
		"في يوم عرفة تتنزّل الرحمات وتطمئن القلوب بالدعاء والرجاء.",
		time.Now().Add(-200*24*time.Hour), 2000, 800, false,
	))
	if got >= 0.5 {
		t.Errorf("religious daily-life post must not fire any blocklist, got %.3f", got)
	}
}

func TestLatinAllCapsRatio_IgnoresArabic(t *testing.T) {
	// Arabic letters don't have case; they must not be counted as
	// either upper or lower in the ratio.
	if got := latinAllCapsRatio("تنبيه HELLO WORLD"); got != 1.0 {
		t.Errorf("expected 1.0 (all Latin letters upper), got %.3f", got)
	}
	if got := latinAllCapsRatio("تنبيه عاجل"); got != 0 {
		t.Errorf("expected 0 (no Latin letters), got %.3f", got)
	}
}

// ── New aggressive heuristics ──────────────────────────────────────

func TestScore_EscortCaption_SweetDreams(t *testing.T) {
	// Verbatim live-feed pattern: short English caption + t.co URL.
	got, breakdown := Score(Compute(Input{
		Text: "Sweet dreams 🥰🥰🥰 https://t.co/upk013KFo2",
	}))
	if got < 0.5 {
		t.Errorf("escort-caption + URL expected >= 0.5, got %.3f breakdown=%v", got, breakdown)
	}
}

func TestScore_EscortCaption_NotFiredOnLongPost(t *testing.T) {
	// "Sweet dreams" inside a longer real post (parent saying goodnight
	// to their kids) must not fire — the rune-count gate (> 40) bars it.
	got, _ := Score(Compute(Input{
		Text: "Just told the kids — sweet dreams my loves, see you in the morning ❤️",
	}))
	if got >= 0.5 {
		t.Errorf("long English post should not fire escort-caption, got %.3f", got)
	}
}

func TestScore_BareUrl_EmojiPrefixCaught(t *testing.T) {
	// "❤️ https://t.co/X" — stripping URLs+emoji leaves nothing. The
	// old 10-rune threshold let this through because the emoji
	// pictograph counted as a rune. Tightened to 15 with emoji
	// stripped — now drops.
	got, _ := Score(Compute(Input{
		Text: "❤️ https://t.co/nX007zkBKy",
	}))
	if got < 0.4 {
		t.Errorf("emoji-prefix + URL expected >= 0.4 (bare_url), got %.3f", got)
	}
}

func TestScore_MedicalFraud_Caught(t *testing.T) {
	// Verbatim from live feed — fake doctor's certificate funnel.
	got, _ := Score(Compute(Input{
		Text: "#سكليف #اجازة #اعذار_طبية #اجازات_مرضية تقرير طبي معتمد 0533286100",
	}))
	if got < 0.7 {
		t.Errorf("medical-fraud ad expected >= 0.7, got %.3f", got)
	}
}

func TestScore_MedicalFraud_NotFiredByLegitTalk(t *testing.T) {
	// Talking about being sick without the classifieds vocabulary
	// must not fire.
	got, _ := Score(Compute(Input{
		Text: "ما زلت تعبان من البرد، رحت للدكتور وأخذ لي علاج بسيط.",
	}))
	if got >= 0.5 {
		t.Errorf("legit illness talk must not fire medical-fraud, got %.3f", got)
	}
}

func TestScore_FurnitureService_PhonePlusKeyword(t *testing.T) {
	// Verbatim live-feed pattern.
	got, _ := Score(Compute(Input{
		Text: "🚛 شراء الأثاث المستعمل بالرياض 🚛 0556192977",
	}))
	if got < 0.55 {
		t.Errorf("furniture-service ad expected >= 0.55, got %.3f", got)
	}
}

func TestScore_FurnitureService_MultipleKeywords_NoPhoneStillFires(t *testing.T) {
	// Aggressive: keyword density alone fires when ≥ 2 distinct
	// vocab terms appear. Catches the "we move + we buy" stack.
	got, _ := Score(Compute(Input{
		Text: "شركة نقل عفش بالرياض - شراء الأثاث المستعمل بسعر مناسب",
	}))
	if got < 0.55 {
		t.Errorf("furniture stack (no phone) expected >= 0.55, got %.3f", got)
	}
}

func TestScore_FurnitureService_NotFiredOnIncidentalMention(t *testing.T) {
	// One incidental keyword without phone or extra vocab — legit.
	got, _ := Score(Compute(Input{
		Text: "بعت غرفة النوم القديمة قبل ما أنتقل للبيت الجديد",
	}))
	if got >= 0.55 {
		t.Errorf("incidental mention must not fire furniture-service, got %.3f", got)
	}
}

func TestScore_SuspiciousHandle_AloneIsSoft(t *testing.T) {
	// Trailing-digits handle alone is a 0.15 penalty — should NOT
	// drop the post on its own (legit users sometimes pick these).
	got, _ := Score(Compute(Input{
		Text:   "اللهم بلغنا تمام العشر وأرزقنا فيها الدعاء المستجاب",
		Handle: "ManalAli1064633",
	}))
	if got >= 0.45 {
		t.Errorf("suspicious handle alone must not drop legit text, got %.3f", got)
	}
	if got < 0.1 {
		t.Errorf("suspicious handle should contribute ~0.15, got %.3f", got)
	}
}

func TestScore_SuspiciousHandle_PlusBareUrl_Drops(t *testing.T) {
	// Auto-gen handle + bare URL is the canonical bot shape.
	// Combined penalties should clear the new 0.45 threshold.
	got, breakdown := Score(Compute(Input{
		Text:   "https://t.co/JAPEa1Pkby",
		Handle: "mumtaza94959855",
	}))
	if got < 0.45 {
		t.Errorf("auto-handle + bare URL expected >= 0.45, got %.3f breakdown=%v", got, breakdown)
	}
}

func TestScore_SuspiciousHandle_NoVowelLong(t *testing.T) {
	// 12+ chars, no vowels — clearly auto-gen.
	if !matchSuspiciousHandle("bwbdlzy28748081") {
		t.Errorf("expected bwbdlzy28748081 to flag as suspicious")
	}
	if !matchSuspiciousHandle("lswdlswd7228114") {
		t.Errorf("expected lswdlswd7228114 to flag as suspicious")
	}
}

func TestScore_SuspiciousHandle_NormalNotFlagged(t *testing.T) {
	// Short readable handle — must not flag.
	if matchSuspiciousHandle("omarss") {
		t.Errorf("omarss must not flag")
	}
	if matchSuspiciousHandle("KhalidT") {
		t.Errorf("KhalidT must not flag")
	}
}

func TestScore_ReligiousRepeat_NotFiredAsSpam(t *testing.T) {
	// "الله أكبر الله أكبر..." chant — must not fire any blocklist
	// despite repeated words. This is THE most common false-positive
	// shape on the live feed.
	got, _ := Score(Compute(Input{
		Text: "الله أكبر الله أكبر الله أكبر لا إله إلا الله الله أكبر الله أكبر ولله الحمد",
	}))
	if got >= 0.45 {
		t.Errorf("religious chant must not fire any blocklist, got %.3f", got)
	}
}
