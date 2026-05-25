package events

import (
	"slices"
	"testing"
)

func TestCompute_TicketsAlone(t *testing.T) {
	s := Compute("تذاكر متاحة الآن لحفل العام")
	if s.Value < 0.5 {
		t.Errorf("tickets keyword alone should clear 0.5, got %.2f", s.Value)
	}
	if !slices.Contains(s.Categories, "ticket") {
		t.Errorf("expected ticket category, got %v", s.Categories)
	}
}

func TestCompute_FestivalWithRegistration(t *testing.T) {
	s := Compute("مهرجان الرياض ينطلق الجمعة، التسجيل مفتوح عبر الرابط")
	// festival (0.5) + registration (0.65) + schedule (0.1) = 1.0 capped
	if s.Value < 0.8 {
		t.Errorf("festival+registration+schedule expected >= 0.8, got %.2f (cats=%v)", s.Value, s.Categories)
	}
	for _, want := range []string{"festival", "registration"} {
		if !slices.Contains(s.Categories, want) {
			t.Errorf("expected %q in categories, got %v", want, s.Categories)
		}
	}
}

func TestCompute_BareScheduleScoresLow(t *testing.T) {
	// "this weekend" alone should NOT push a tweet into event territory.
	s := Compute("this weekend was crazy")
	if s.Value >= 0.5 {
		t.Errorf("schedule-only signal should stay under 0.5, got %.2f", s.Value)
	}
}

func TestCompute_PlainNewsZero(t *testing.T) {
	s := Compute("اللهم انصر إخواننا المظلومين في كل مكان")
	if s.Value != 0 {
		t.Errorf("non-event tweet should score 0, got %.2f cats=%v", s.Value, s.Categories)
	}
}

func TestCompute_WorkshopBootcamp(t *testing.T) {
	s := Compute("Join our masterclass on Saudi vision 2030 — sign up via link")
	if s.Value < 0.6 {
		t.Errorf("masterclass+sign-up expected >= 0.6, got %.2f", s.Value)
	}
}

func TestCompute_SameCategoryNoStacking(t *testing.T) {
	// Three ticket keywords should still only credit one category.
	s := Compute("تذاكر متاحة! tickets! احجز الآن!")
	if got := len(s.Categories); got != 1 {
		t.Errorf("repeated ticket keywords should still yield 1 category, got %d (%v)", got, s.Categories)
	}
}

func TestCompute_ClampedToOne(t *testing.T) {
	s := Compute("تذاكر مهرجان حفل مؤتمر ورشة محاضرة افتتاح registration")
	if s.Value != 1.0 {
		t.Errorf("expected score clamped to 1.0, got %.2f", s.Value)
	}
}
