package server

import (
	"context"
	"time"
)

// FixtureSource serves a hand-crafted list of plausible tweets per country
// so the Android client and the contract can be exercised before the
// scraper is wired in. Replaced wholesale by package scrape in Phase 2;
// kept around afterwards as a fallback when the live source errors.
type FixtureSource struct{}

func NewFixtureSource() *FixtureSource { return &FixtureSource{} }

func (f *FixtureSource) Feed(_ context.Context, country Country) ([]Tweet, error) {
	now := time.Now().UTC()
	switch country {
	case CountryKSA:
		return f.ksa(now), nil
	case CountryEgypt:
		return f.egypt(now), nil
	default:
		return nil, ErrUnknownCountry
	}
}

func (f *FixtureSource) ksa(now time.Time) []Tweet {
	return []Tweet{
		{
			ID:           "ksa-1",
			Author:       "وزارة الداخلية",
			Handle:       "MOISaudiArabia",
			Text:         "تم تشغيل خدمة جديدة لتجديد الإقامة من خلال تطبيق أبشر — لا حاجة لزيارة الجوازات.",
			CreatedAt:    now.Add(-20 * time.Minute),
			Lang:         "ar",
			Place:        "Riyadh, SA",
			Country:      CountryKSA,
			ReplyCount:   142,
			LikeCount:    2103,
			RetweetCount: 587,
		},
		{
			ID:           "ksa-2",
			Author:       "Saudi Arabia",
			Handle:       "Saudi_Gazette",
			Text:         "NEOM unveils first all-electric coastal city section as part of its 2030 milestone delivery plan.",
			CreatedAt:    now.Add(-45 * time.Minute),
			Lang:         "en",
			Place:        "Tabuk, SA",
			Country:      CountryKSA,
			ReplyCount:   28,
			LikeCount:    340,
			RetweetCount: 95,
		},
		{
			ID:           "ksa-3",
			Author:       "هيئة الأرصاد",
			Handle:       "NCM_KSA",
			Text:         "تنبيه: موجة غبار متوقعة على شرق الرياض بعد الساعة الرابعة عصراً.",
			CreatedAt:    now.Add(-1 * time.Hour),
			Lang:         "ar",
			Place:        "Riyadh, SA",
			Country:      CountryKSA,
			ReplyCount:   12,
			LikeCount:    178,
			RetweetCount: 64,
		},
	}
}

func (f *FixtureSource) egypt(now time.Time) []Tweet {
	return []Tweet{
		{
			ID:           "eg-1",
			Author:       "AhramOnline",
			Handle:       "AhramOnline",
			Text:         "Egypt's central bank holds interest rates steady citing easing inflation outlook.",
			CreatedAt:    now.Add(-15 * time.Minute),
			Lang:         "en",
			Place:        "Cairo, EG",
			Country:      CountryEgypt,
			ReplyCount:   46,
			LikeCount:    512,
			RetweetCount: 121,
		},
		{
			ID:           "eg-2",
			Author:       "اليوم السابع",
			Handle:       "youm7",
			Text:         "افتتاح المتحف المصري الكبير: تجربة زوار جديدة تجمع بين الواقع المعزز والإرشاد بالذكاء الاصطناعي.",
			CreatedAt:    now.Add(-1 * time.Hour),
			Lang:         "ar",
			Place:        "Giza, EG",
			Country:      CountryEgypt,
			ReplyCount:   89,
			LikeCount:    1402,
			RetweetCount: 333,
		},
	}
}
