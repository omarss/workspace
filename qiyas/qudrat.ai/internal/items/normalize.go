// Package items owns the item-bank domain logic: Arabic normalization,
// dedup-friendly hashing, and (later) the read-only HTTP surface for
// serving questions to learners.
//
// Normalization rules implement spec §9.1: strip tatweel, normalize alef
// forms (إ أ آ ٱ → ا), normalize ya / alif maqsurah (ى → ي), normalize
// ta marbuta (ة → ه), strip Arabic diacritics, normalize Arabic-Indic
// digits to Western digits, collapse whitespace, and lowercase any Latin.
//
// Two questions that differ only in those surface details (a writer typed
// `كتاب رقم ٤٢` vs `كــتاب رقم 42`) hash to the same value, so the items
// table's UNIQUE constraint on normalized_text_hash rejects the duplicate.
package items

import (
	"crypto/sha256"
	"encoding/hex"
	"strings"
	"unicode"
)

// arabicReplacer canonicalizes the alef family, hamza-bearing letters,
// alif maqsurah, ta marbuta, and Arabic-Indic + Eastern Arabic-Indic
// digits in a single pass. strings.Replacer is O(n*k) in the rune table
// but k stays tiny here so it's faster than per-rune branching.
var arabicReplacer = strings.NewReplacer(
	// Alef variants → bare alef.
	"إ", "ا",
	"أ", "ا",
	"آ", "ا",
	"ٱ", "ا",
	// Alif maqsurah → ya.
	"ى", "ي",
	// Ta marbuta → ha. Spec §9.1 lists "where appropriate"; for hashing
	// we always collapse so "مدرسة" and "مدرسه" hash equal.
	"ة", "ه",
	// Hamza-bearing → bare letter.
	"ئ", "ي",
	"ؤ", "و",
	"ء", "",
	// Arabic-Indic digits → Western.
	"٠", "0", "١", "1", "٢", "2", "٣", "3", "٤", "4",
	"٥", "5", "٦", "6", "٧", "7", "٨", "8", "٩", "9",
	// Eastern Arabic-Indic digits (Persian) → Western.
	"۰", "0", "۱", "1", "۲", "2", "۳", "3", "۴", "4",
	"۵", "5", "۶", "6", "۷", "7", "۸", "8", "۹", "9",
	// Tatweel (kashida) is a typographic stretch with no semantic value.
	"ـ", "",
)

// NormalizeArabic returns s with Arabic diacritics, tatweel, and surface
// variants of alef/ya/ta-marbuta/digits collapsed to canonical forms,
// whitespace runs reduced to a single space, and the result trimmed +
// lowercased. Suitable as input to Hash.
func NormalizeArabic(s string) string {
	s = arabicReplacer.Replace(s)

	// Strip Arabic diacritics (the Mn category covers harakat and friends)
	// in one allocation rather than running another Replacer.
	var b strings.Builder
	b.Grow(len(s))
	for _, r := range s {
		if unicode.Is(unicode.Mn, r) {
			continue
		}
		b.WriteRune(r)
	}
	s = b.String()

	// Collapse whitespace runs to a single space.
	s = strings.Join(strings.Fields(s), " ")
	return strings.ToLower(s)
}

// Hash returns a hex SHA-256 of NormalizeArabic(s). Stable across processes.
func Hash(s string) string {
	sum := sha256.Sum256([]byte(NormalizeArabic(s)))
	return hex.EncodeToString(sum[:])
}

// HashChoices returns a hash that depends on choice content AND order, so
// re-ordering choices changes the hash. Order matters for dedup because a
// student would experience reordered choices as a different question.
func HashChoices(a, b, c, d string) string {
	joined := NormalizeArabic(a) + "\x1e" + NormalizeArabic(b) + "\x1e" + NormalizeArabic(c) + "\x1e" + NormalizeArabic(d)
	sum := sha256.Sum256([]byte(joined))
	return hex.EncodeToString(sum[:])
}
