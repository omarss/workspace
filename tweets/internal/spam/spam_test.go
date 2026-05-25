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
