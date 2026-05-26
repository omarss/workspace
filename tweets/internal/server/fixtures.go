package server

import (
	"context"
	"strings"
	"time"
)

// FixtureSource serves a hand-crafted list of plausible tweets per country
// so the Android client and the contract can be exercised before the
// scraper is wired in. Replaced wholesale by package scrape in Phase 2;
// kept around afterwards as a fallback when the live source errors.
type FixtureSource struct{}

func NewFixtureSource() *FixtureSource { return &FixtureSource{} }

func (f *FixtureSource) Feed(_ context.Context, req FeedRequest) (FeedResult, error) {
	now := time.Now().UTC()
	out := make([]Tweet, 0, 6)
	for _, country := range req.Countries {
		switch country {
		case CountryKSA:
			out = append(out, f.ksa(now)...)
		case CountryEgypt:
			out = append(out, f.egypt(now)...)
		default:
			return FeedResult{}, ErrUnknownCountry
		}
	}
	// Apply city filter when set; otherwise pass everything.
	if len(req.Cities) > 0 {
		filtered := out[:0]
		for _, tw := range out {
			if matchesAnyCity(tw.Place, req.Cities) {
				filtered = append(filtered, tw)
			}
		}
		out = filtered
	}
	// Apply keyword query when set.
	if terms := tokenizeFixtureQuery(req.Query); len(terms) > 0 {
		filtered := out[:0]
		for _, tw := range out {
			if matchesAllFixtureTerms(tw.Text, terms) {
				filtered = append(filtered, tw)
			}
		}
		out = filtered
	}
	// Honour cursor + limit so fixtures behave like the store does.
	if !req.Cursor.IsZero() {
		filtered := out[:0]
		for _, tw := range out {
			if tw.CreatedAt.Before(req.Cursor) {
				filtered = append(filtered, tw)
			}
		}
		out = filtered
	}
	limit := req.Limit
	if limit <= 0 {
		limit = 60
	}
	if len(out) > limit {
		out = out[:limit]
	}
	return FeedResult{Tweets: out}, nil
}

// matchesAnyCity returns true when place contains any of the
// case-insensitive substrings in cities. Used by both the fixture
// source (here) and the store source (store_source.go).
func matchesAnyCity(place string, cities []string) bool {
	low := strings.ToLower(place)
	for _, c := range cities {
		if c == "" {
			continue
		}
		if strings.Contains(low, strings.ToLower(c)) {
			return true
		}
	}
	return false
}

// Local copies of the store package's tokenize / match helpers so the
// fixture source doesn't import store (which would pull SQLite into
// any binary that just wants the fallback). The store version is the
// source of truth; keep them aligned.
func tokenizeFixtureQuery(q string) []string {
	q = strings.TrimSpace(q)
	if q == "" {
		return nil
	}
	return strings.Fields(strings.ToLower(q))
}

func matchesAllFixtureTerms(text string, terms []string) bool {
	low := strings.ToLower(text)
	for _, t := range terms {
		if !strings.Contains(low, t) {
			return false
		}
	}
	return true
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
