package items

import "testing"

func TestNormalizeArabic_StripsTatweelAndDiacritics(t *testing.T) {
	t.Parallel()
	in := "كــــتــب" // tatweel inside
	got := NormalizeArabic(in)
	if got != "كتب" {
		t.Errorf("tatweel: got %q, want %q", got, "كتب")
	}

	// Diacritics removed.
	got = NormalizeArabic("كَتَبَ")
	if got != "كتب" {
		t.Errorf("diacritics: got %q, want %q", got, "كتب")
	}
}

func TestNormalizeArabic_NormalizesAlef(t *testing.T) {
	t.Parallel()
	cases := []string{"إ", "أ", "آ", "ٱ"}
	for _, c := range cases {
		if got := NormalizeArabic(c); got != "ا" {
			t.Errorf("alef variant %q: got %q, want ا", c, got)
		}
	}
}

func TestNormalizeArabic_NormalizesYaTaAndHamza(t *testing.T) {
	t.Parallel()
	if got := NormalizeArabic("ى"); got != "ي" {
		t.Errorf("alif maqsurah: got %q", got)
	}
	if got := NormalizeArabic("ة"); got != "ه" {
		t.Errorf("ta marbuta: got %q", got)
	}
	if got := NormalizeArabic("ئ"); got != "ي" {
		t.Errorf("hamza-on-ya: got %q", got)
	}
	if got := NormalizeArabic("ؤ"); got != "و" {
		t.Errorf("hamza-on-waw: got %q", got)
	}
}

func TestNormalizeArabic_NormalizesDigits(t *testing.T) {
	t.Parallel()
	if got := NormalizeArabic("١٢٣٤٥٦٧٨٩٠"); got != "1234567890" {
		t.Errorf("arabic-indic digits: got %q", got)
	}
	if got := NormalizeArabic("۱۲۳۴۵۶۷۸۹۰"); got != "1234567890" {
		t.Errorf("eastern arabic-indic digits: got %q", got)
	}
}

func TestNormalizeArabic_CollapsesWhitespace(t *testing.T) {
	t.Parallel()
	in := "  hello   world\nfoo\tbar  "
	if got := NormalizeArabic(in); got != "hello world foo bar" {
		t.Errorf("got %q", got)
	}
}

// Two Arabic strings that differ only by tatweel + alef variant + digit
// script must produce the same hash. This is the core dedup invariant.
func TestHash_EquivalentInputsCollide(t *testing.T) {
	t.Parallel()
	a := "كــتاب رقم ٤٢"
	b := "كتاب رقم 42"
	if Hash(a) != Hash(b) {
		t.Fatalf("hashes diverge: a=%q b=%q", Hash(a), Hash(b))
	}
}

func TestHash_DifferentInputsDiverge(t *testing.T) {
	t.Parallel()
	if Hash("كتاب") == Hash("قلم") {
		t.Fatal("distinct inputs hashed to the same value")
	}
}

func TestHashChoices_OrderMatters(t *testing.T) {
	t.Parallel()
	h1 := HashChoices("a", "b", "c", "d")
	h2 := HashChoices("b", "a", "c", "d")
	if h1 == h2 {
		t.Fatal("choice order must affect the hash")
	}
}
