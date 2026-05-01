// Package grading hosts the language-agnostic pieces of the score pipeline:
// anti-cheat checks, similarity helpers, and (in step 6) the sandbox runner
// API. Provider-specific scoring (test execution, image SSIM, etc.) lives
// in subpackages.
package grading

import (
	"strings"
	"unicode"
)

// DefaultNGramSize is the n-gram length the strip-the-target rule uses. 5
// catches any meaningful copy-paste of the target while letting users still
// reference common syntactic words ("def", "return"). Smaller n is too
// strict; larger n misses paraphrases.
const DefaultNGramSize = 5

// DefaultMaxOverlap is the threshold above which a prompt is rejected as a
// thinly-disguised copy of the target. 30% comes from manual calibration on
// a few hand-curated targets — tune as the corpus grows.
const DefaultMaxOverlap = 0.30

// NGramOverlap returns the fraction of n-grams in `prompt` that also appear
// in `target`, in [0, 1]. Both strings are normalized — lowercased,
// whitespace-collapsed — so cosmetic differences don't change the result.
//
// If `prompt` has fewer than n tokens the result is 0 (nothing to overlap).
func NGramOverlap(prompt, target string, n int) float64 {
	if n < 1 {
		n = 1
	}
	pT := tokenize(prompt)
	tT := tokenize(target)
	if len(pT) < n {
		return 0
	}

	targetSet := make(map[string]struct{})
	for _, ng := range buildNGrams(tT, n) {
		targetSet[ng] = struct{}{}
	}

	promptGrams := buildNGrams(pT, n)
	if len(promptGrams) == 0 {
		return 0
	}
	matched := 0
	for _, ng := range promptGrams {
		if _, ok := targetSet[ng]; ok {
			matched++
		}
	}
	return float64(matched) / float64(len(promptGrams))
}

// IsTargetCopy returns true when prompt overlaps target enough that we
// suspect copy-paste. Defaults can be overridden via the size+threshold
// args; pass 0 to use DefaultNGramSize / DefaultMaxOverlap.
func IsTargetCopy(prompt, target string, size int, threshold float64) bool {
	if size <= 0 {
		size = DefaultNGramSize
	}
	if threshold <= 0 {
		threshold = DefaultMaxOverlap
	}
	return NGramOverlap(prompt, target, size) > threshold
}

// tokenize splits on whitespace and any non-letter/digit/punctuation rune,
// lowercasing each token. Punctuation that's part of code syntax (e.g. `(`,
// `:`) is its own token so n-gram matching catches `def f ( x ) :` style
// near-identical lines.
func tokenize(s string) []string {
	if s == "" {
		return nil
	}
	var out []string
	var cur strings.Builder
	flush := func() {
		if cur.Len() > 0 {
			out = append(out, cur.String())
			cur.Reset()
		}
	}
	for _, r := range strings.ToLower(s) {
		switch {
		case unicode.IsLetter(r) || unicode.IsDigit(r) || r == '_':
			cur.WriteRune(r)
		case unicode.IsSpace(r):
			flush()
		default:
			// Punctuation tokens stand alone.
			flush()
			out = append(out, string(r))
		}
	}
	flush()
	return out
}

func buildNGrams(tokens []string, n int) []string {
	if len(tokens) < n {
		return nil
	}
	out := make([]string, 0, len(tokens)-n+1)
	for i := 0; i+n <= len(tokens); i++ {
		out = append(out, strings.Join(tokens[i:i+n], " "))
	}
	return out
}
