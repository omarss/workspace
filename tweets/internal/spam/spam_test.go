package spam

import (
	"testing"
	"time"
)

func TestScore_Clean(t *testing.T) {
	got, _ := Score(Compute(
		"تنبيه: موجة غبار متوقعة على شرق الرياض بعد الساعة الرابعة عصراً.",
		time.Now().Add(-365*24*time.Hour), 5000, 200, false,
	))
	if got > 0.05 {
		t.Errorf("clean tweet scored too high: %.3f", got)
	}
}

func TestScore_HashtagSpam(t *testing.T) {
	got, breakdown := Score(Compute(
		"Buy now! #crypto #moon #pumpit #100x #freelambo #defi #bullrun",
		time.Time{}, 0, 0, false,
	))
	if got < 0.2 {
		t.Errorf("hashtag-stuffed tweet should score >= 0.2, got %.3f (breakdown=%v)", got, breakdown)
	}
}

func TestScore_LinkSpam(t *testing.T) {
	got, _ := Score(Compute(
		"check this https://a.com https://b.com https://c.com great offer",
		time.Time{}, 0, 0, false,
	))
	if got < 0.2 {
		t.Errorf("3-link tweet should score >= 0.2, got %.3f", got)
	}
}

func TestScore_NewAccountAllCaps(t *testing.T) {
	got, breakdown := Score(Compute(
		"DOUBLE YOUR MONEY OVERNIGHT — LIMITED SLOTS, ACT NOW BEFORE THEY ARE GONE",
		time.Now().Add(-5*24*time.Hour), 12, 8000, false,
	))
	if got < 0.3 {
		t.Errorf("new-account all-caps should score >= 0.3, got %.3f (breakdown=%v)", got, breakdown)
	}
}

func TestScore_DuplicateRecentHeavyPenalty(t *testing.T) {
	got, _ := Score(Compute(
		"Visit my store!", time.Time{}, 0, 0, true,
	))
	if got < 0.3 {
		t.Errorf("duplicate-recent should score >= 0.3 alone, got %.3f", got)
	}
}

func TestScore_ClampedToOne(t *testing.T) {
	got, _ := Score(Compute(
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
	got, breakdown := Score(Compute(
		"#Jeddah_VlPmassage #Jeddah_Fullbodymassage #ladyboy_saudi #Jeddah_massage_moroccan_bath  https://t.co/x",
		time.Time{}, 0, 0, false,
	))
	if got < 0.7 {
		t.Errorf("adult promo should clear 0.7, got %.3f breakdown=%v", got, breakdown)
	}
}

func TestScore_CouponBracketBlocklist(t *testing.T) {
	// Verbatim coupon-bracket pattern observed in live KSA feed.
	got, breakdown := Score(Compute(
		"⎐كُود⎐⎐ايهرب⎐ايهيرب اهرب ⊵IQH8946⊴",
		time.Time{}, 0, 0, false,
	))
	if got < 0.6 {
		t.Errorf("coupon-bracket should clear 0.6, got %.3f breakdown=%v", got, breakdown)
	}
}

func TestScore_CouponKeywordBlocklist(t *testing.T) {
	// AliExpress / Noon / Namshi coupon-code dropshipping text.
	got, _ := Score(Compute(
		"كوبون خصم لطلبك من aliexpress احصل عليه الآن!",
		time.Time{}, 0, 0, false,
	))
	if got < 0.6 {
		t.Errorf("coupon-keyword should clear 0.6, got %.3f", got)
	}
}

func TestScore_LocalBizAdBlocklist(t *testing.T) {
	// Saudi phone + butcher-service keyword — observed pattern.
	got, _ := Score(Compute(
		"قصاب ماهر بالرياض 0533286100 قصاب شمال الرياض",
		time.Time{}, 0, 0, false,
	))
	if got < 0.55 {
		t.Errorf("local-biz ad should clear 0.55, got %.3f", got)
	}
}

func TestScore_LocalBizAd_PhoneAloneNotSpam(t *testing.T) {
	// Same phone format but no service keyword — legitimate, must not fire.
	got, _ := Score(Compute(
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
	got, _ := Score(Compute(
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
	got, _ := Score(Compute(
		"The Custodian of the Two Holy Mosques chaired today's cabinet meeting.",
		time.Time{}, 0, 0, false,
	))
	if got >= 0.5 {
		t.Errorf("single political-keyword news quote must not fire, got %.3f", got)
	}
}

func TestScore_AdultSoftPromo(t *testing.T) {
	// Verbatim "Come to me" pattern observed in live feed.
	got, _ := Score(Compute(
		"مساج في مدينة جدة   مساج في مدينة الدمام   Come to me 24/24🦋 💃💃💃 https://t.co/x https://t.co/y",
		time.Time{}, 0, 0, false,
	))
	if got < 0.7 {
		t.Errorf("adult soft-promo expected >= 0.7, got %.3f", got)
	}
}

func TestScore_OffRegionDubaiRental(t *testing.T) {
	// Verbatim Dubai car-rental tagged-as-KSA pattern.
	got, _ := Score(Compute(
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
	got, _ := Score(Compute(
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
	got, _ := Score(Compute(
		"أبحث عن تأجير سيارة في الرياض لمدة أسبوع، أي توصيات؟",
		time.Time{}, 0, 0, false,
	))
	if got >= 0.5 {
		t.Errorf("KSA rental query must not fire off-region promo, got %.3f", got)
	}
}

func TestScore_LegitimateContentNotFlagged(t *testing.T) {
	// Spot-check: religious daily-life post should pass with a low score.
	got, _ := Score(Compute(
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
