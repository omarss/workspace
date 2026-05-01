package grading

import "testing"

func TestNGramOverlap_FullCopyIsOne(t *testing.T) {
	t.Parallel()
	target := "def add(a, b): return a + b"
	got := NGramOverlap(target, target, 3)
	if got != 1.0 {
		t.Fatalf("self overlap = %v, want 1.0", got)
	}
}

func TestNGramOverlap_DisjointIsZero(t *testing.T) {
	t.Parallel()
	a := "the quick brown fox"
	b := "lorem ipsum dolor sit amet consectetur"
	if got := NGramOverlap(a, b, 3); got != 0 {
		t.Fatalf("disjoint overlap = %v, want 0", got)
	}
}

func TestNGramOverlap_PartialMatch(t *testing.T) {
	t.Parallel()
	target := "def add a b return a + b"
	prompt := "def add a b: pass"
	got := NGramOverlap(prompt, target, 3)
	// At least one matching trigram ("def add a") expected; some won't match.
	if got <= 0 || got >= 1 {
		t.Fatalf("partial overlap = %v, want in (0,1)", got)
	}
}

func TestNGramOverlap_PromptTooShortIsZero(t *testing.T) {
	t.Parallel()
	if got := NGramOverlap("a b", "a b c d e", 5); got != 0 {
		t.Fatalf("short prompt overlap = %v, want 0", got)
	}
}

func TestIsTargetCopy_DetectsObviousCopy(t *testing.T) {
	t.Parallel()
	target := "def factorial(n): return 1 if n <= 1 else n * factorial(n-1)"
	prompt := "Make me " + target // pretty obvious paste
	if !IsTargetCopy(prompt, target, 0, 0) {
		t.Fatalf("expected target copy to be flagged")
	}
}

func TestIsTargetCopy_AcceptsNaturalDescription(t *testing.T) {
	t.Parallel()
	target := "def factorial(n): return 1 if n <= 1 else n * factorial(n-1)"
	prompt := "Write a recursive function in Python that returns the factorial of a non-negative integer."
	if IsTargetCopy(prompt, target, 0, 0) {
		t.Fatalf("natural description should not trip the rule")
	}
}

func TestNGramOverlap_PunctuationIsTokenized(t *testing.T) {
	t.Parallel()
	a := "def f(x): pass"
	b := "def g(y): pass"
	// "( ) : pass" tail and "def" all appear in both but vars differ.
	if got := NGramOverlap(a, b, 2); got <= 0 {
		t.Fatalf("expected nonzero overlap on shared punctuation/keywords, got %v", got)
	}
}
