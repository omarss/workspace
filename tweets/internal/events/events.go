// Package events scores a tweet for "is this about an event you might
// want to attend or register for?" The Feed tab biases ranking by
// this score so events float to the top while still letting general
// location-tagged posts through.
//
// Vocabulary is curated for the Saudi + Egyptian context — concerts,
// festivals, conferences, sports, workshops, public lectures, plus
// the Arabic verbs that signal "doors open / book your ticket / link
// in bio". Keywords match case-insensitively against the raw tweet
// text. Two co-occurring matches score higher than two matches of the
// same root.
package events

import (
	"sort"
	"strings"
)

// Keyword carries the matchable string + its category. Categories are
// surfaced to the UI so it can render a small badge ("🎟 tickets",
// "🎤 concert", etc.) on event-tagged rows.
type Keyword struct {
	Text     string // case-folded matchable substring
	Category string // e.g. "ticket", "concert", "workshop"
	Weight   float64
}

// Score is the per-tweet result: the rounded [0, 1] event-likelihood
// plus the matched keyword set (deduped by category) so the UI can
// surface what made the score what it is.
type Score struct {
	Value      float64
	Categories []string
}

// Compute walks the tweet text against the vocabulary. Score grows
// with each unique category matched (not per keyword) so a tweet
// hitting "tickets" twice doesn't pile up; one hitting "tickets" +
// "concert" + "registration" does. Capped at 1.0.
func Compute(text string) Score {
	low := strings.ToLower(text)
	seen := map[string]float64{}
	for _, k := range vocab {
		if !strings.Contains(low, k.Text) {
			continue
		}
		// Keep the highest weight per category so a strong keyword
		// isn't shadowed by a weak co-occurring one.
		if cur, ok := seen[k.Category]; !ok || k.Weight > cur {
			seen[k.Category] = k.Weight
		}
	}
	if len(seen) == 0 {
		return Score{}
	}
	var total float64
	cats := make([]string, 0, len(seen))
	for c, w := range seen {
		total += w
		cats = append(cats, c)
	}
	sort.Strings(cats)
	if total > 1.0 {
		total = 1.0
	}
	return Score{Value: total, Categories: cats}
}

// Vocabulary, grouped by category. Weights are tuned so a single
// strong keyword (e.g. "تذاكر متاحة" / "tickets available") pushes
// a tweet over the 0.5 mark on its own, while weak signals like the
// bare word "حفل" need a co-occurring category to clear that.
var vocab = []Keyword{
	// ── TICKETS ─────────────────────────────────────────────────
	{"تذاكر", "ticket", 0.5},
	{"تذكرة", "ticket", 0.45},
	{"tickets", "ticket", 0.5},
	{"ticket", "ticket", 0.4},
	{"احجز", "ticket", 0.45}, // "book"
	{"book now", "ticket", 0.55},
	{"حجز", "ticket", 0.35},

	// ── REGISTRATION ────────────────────────────────────────────
	{"تسجيل", "registration", 0.5},
	{"سجل الآن", "registration", 0.6},
	{"سجلوا", "registration", 0.55},
	{"التسجيل مفتوح", "registration", 0.65},
	{"registration open", "registration", 0.6},
	{"register now", "registration", 0.55},
	{"sign up", "registration", 0.45},
	{"رابط التسجيل", "registration", 0.6},

	// ── CONCERTS / SHOWS ────────────────────────────────────────
	{"حفلة", "concert", 0.4},
	{"حفل", "concert", 0.3},
	{"حفل غنائي", "concert", 0.55},
	{"حفلات", "concert", 0.45},
	{"concert", "concert", 0.5},
	{"live show", "concert", 0.5},

	// ── FESTIVALS ───────────────────────────────────────────────
	{"مهرجان", "festival", 0.5},
	{"مهرجانات", "festival", 0.5},
	{"festival", "festival", 0.5},

	// ── CONFERENCES / SUMMITS ───────────────────────────────────
	{"مؤتمر", "conference", 0.5},
	{"قمة", "conference", 0.4},
	{"ملتقى", "conference", 0.4},
	{"conference", "conference", 0.5},
	{"summit", "conference", 0.45},
	{"expo", "conference", 0.4},
	{"معرض", "conference", 0.35},

	// ── WORKSHOPS / COURSES ─────────────────────────────────────
	{"ورشة", "workshop", 0.4},
	{"ورشة عمل", "workshop", 0.5},
	{"دورة", "workshop", 0.35},
	{"دورة تدريبية", "workshop", 0.55},
	{"بوت كامب", "workshop", 0.45},
	{"workshop", "workshop", 0.5},
	{"bootcamp", "workshop", 0.5},
	{"masterclass", "workshop", 0.55},
	{"course", "workshop", 0.3},

	// ── SPORTS EVENTS ───────────────────────────────────────────
	{"مباراة", "sports", 0.4},
	{"بطولة", "sports", 0.45},
	{"دوري", "sports", 0.35},
	{"سباق", "sports", 0.4},
	{"match", "sports", 0.3},
	{"tournament", "sports", 0.4},
	{"derby", "sports", 0.4},

	// ── LECTURES / SEMINARS ─────────────────────────────────────
	{"ندوة", "talk", 0.4},
	{"محاضرة", "talk", 0.4},
	{"جلسة حوارية", "talk", 0.5},
	{"seminar", "talk", 0.45},
	{"lecture", "talk", 0.4},
	{"panel discussion", "talk", 0.5},

	// ── EXHIBITIONS / OPENINGS ──────────────────────────────────
	{"افتتاح", "opening", 0.45},
	{"افتتاح رسمي", "opening", 0.55},
	{"grand opening", "opening", 0.55},
	{"opening", "opening", 0.3},
	{"now open", "opening", 0.45},

	// ── DATE / TIME SIGNALS ─────────────────────────────────────
	// These boost when they co-occur with a category above; they don't
	// score on their own (no category), so we tie them to a synthetic
	// "schedule" category that adds weight to event-like posts.
	{"الموعد", "schedule", 0.15},
	{"مواعيد", "schedule", 0.15},
	{"يوم الجمعة", "schedule", 0.1},
	{"يوم السبت", "schedule", 0.1},
	{"this saturday", "schedule", 0.15},
	{"this friday", "schedule", 0.15},
	{"this weekend", "schedule", 0.2},
	{"tomorrow", "schedule", 0.1},
	{"غداً", "schedule", 0.1},

	// ── VENUE PROMPTS ───────────────────────────────────────────
	{"الموقع", "venue", 0.1},
	{"المكان", "venue", 0.1},
	{"venue", "venue", 0.15},
	{"location", "venue", 0.1},
}
