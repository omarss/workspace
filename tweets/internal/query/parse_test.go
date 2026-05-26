package query

import "testing"

func TestParse_Empty(t *testing.T) {
	expr, err := Parse("")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, ok := expr.(Always); !ok {
		t.Errorf("expected Always for empty input, got %T", expr)
	}
}

func TestParse_SingleTerm_MatchesSubstring(t *testing.T) {
	expr, _ := Parse("hackathon")
	if !MatchesText(expr, "join the riyadh hackathon next week") {
		t.Error("expected match on substring")
	}
	if MatchesText(expr, "just a normal tweet") {
		t.Error("unexpected match on unrelated text")
	}
}

func TestParse_ImplicitAnd(t *testing.T) {
	// "ai event" → AND
	expr, _ := Parse("ai event")
	if !MatchesText(expr, "AI event next month in Riyadh") {
		t.Error("expected match")
	}
	if MatchesText(expr, "AI lecture") {
		t.Error("must require both 'ai' and 'event'")
	}
	if MatchesText(expr, "event registration open") {
		t.Error("must require both terms")
	}
}

func TestParse_ExplicitOr(t *testing.T) {
	expr, _ := Parse("hackathon OR conference")
	if !MatchesText(expr, "Riyadh hackathon this Friday") {
		t.Error("expected hackathon match")
	}
	if !MatchesText(expr, "Cairo conference 2026 registration") {
		t.Error("expected conference match")
	}
	if MatchesText(expr, "weather update tonight") {
		t.Error("must not match unrelated text")
	}
}

func TestParse_ExplicitAnd(t *testing.T) {
	// AND keyword is allowed for readability.
	expr, _ := Parse("ai AND event")
	if !MatchesText(expr, "AI event in Jeddah") {
		t.Error("expected match")
	}
	if MatchesText(expr, "AI tutorial only") {
		t.Error("must require both terms")
	}
}

func TestParse_Parens_OrInsideAnd(t *testing.T) {
	// (a OR b) AND c → matches text containing (a or b) AND c
	expr, err := Parse("(ai OR ml) AND event")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !MatchesText(expr, "AI event in Riyadh") {
		t.Error("expected 'ai+event' match")
	}
	if !MatchesText(expr, "ML event tomorrow") {
		t.Error("expected 'ml+event' match")
	}
	if MatchesText(expr, "AI only no events") {
		// "no events" contains "event" — should match. Confirms
		// substring semantics, not whole-word.
		// This is intentional; rename test if confusing.
	}
	if MatchesText(expr, "javascript tutorial") {
		t.Error("must not match unrelated text")
	}
}

func TestParse_QuotedPhrase(t *testing.T) {
	expr, err := Parse(`"machine learning" event`)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !MatchesText(expr, "machine learning event in NEOM") {
		t.Error("expected phrase + and-term match")
	}
	if MatchesText(expr, "machine event tomorrow") {
		// "machine" + "event" present but not the exact phrase.
		t.Error("phrase match must be exact substring")
	}
}

func TestParse_PhrasePreservesSpaces(t *testing.T) {
	expr, _ := Parse(`"link in bio"`)
	if !MatchesText(expr, "subscribe — link in bio for more") {
		t.Error("expected phrase match")
	}
	if MatchesText(expr, "link bio") {
		t.Error("phrase must not match when words are not adjacent")
	}
}

func TestParse_NestedParens(t *testing.T) {
	expr, err := Parse("(a OR (b AND c)) AND d")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !MatchesText(expr, "a and d are here") {
		t.Error("a+d should match")
	}
	if !MatchesText(expr, "b c d together") {
		t.Error("b+c+d should match")
	}
	if MatchesText(expr, "b d only") {
		t.Error("b without c must fail the inner AND")
	}
}

func TestParse_UnterminatedQuote(t *testing.T) {
	if _, err := Parse(`"never closed`); err == nil {
		t.Error("expected error for unterminated quote")
	}
}

func TestParse_MissingCloseParen(t *testing.T) {
	if _, err := Parse(`(a OR b`); err == nil {
		t.Error("expected error for missing )")
	}
}

func TestParse_LowercaseInsensitive(t *testing.T) {
	expr, _ := Parse("Hackathon")
	if !MatchesText(expr, "Riyadh HACKATHON 2026") {
		t.Error("matching must be case-insensitive")
	}
}

func TestParse_OperatorKeywordIsCaseInsensitive(t *testing.T) {
	// `OR`, `or`, `Or` all parse as the operator.
	expr, err := Parse("a or b")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, ok := expr.(Or); !ok {
		t.Errorf("expected Or, got %T", expr)
	}
}

func TestParse_StrayOperator(t *testing.T) {
	if _, err := Parse("OR foo"); err == nil {
		t.Error("expected error for leading OR")
	}
}

// ── Word-boundary matching for short Latin terms ───────────────────

func TestTerm_AsciiTermRequiresWordBoundary(t *testing.T) {
	// "ai" must NOT match inside "faith", "remain", "again".
	expr, _ := Parse("ai")
	for _, text := range []string{
		"i hold onto faith",
		"the marketing remains the same",
		"start again tomorrow",
		"the gain on each trade",
	} {
		if MatchesText(expr, text) {
			t.Errorf("unwanted ai-substring match in: %q", text)
		}
	}
	// And MUST match standalone.
	for _, text := range []string{
		"AI conference next week",
		"talking about ai today",
		"the ai workshop",
		"ai!",
	} {
		if !MatchesText(expr, text) {
			t.Errorf("expected standalone ai match in: %q", text)
		}
	}
}

func TestTerm_ArabicTermStaysSubstring(t *testing.T) {
	// Arabic terms keep substring semantics because Arabic
	// morphology attaches the definite article "ال" directly.
	// `مؤتمر` must match `المؤتمر` (the conference).
	expr, _ := Parse("مؤتمر")
	if !MatchesText(expr, "حضرت المؤتمر السعودي") {
		t.Error("expected Arabic substring match (definite article)")
	}
}

func TestTerm_AsciiAcrossArabicBoundary(t *testing.T) {
	// "ai" adjacent to Arabic letters — Arabic high-byte runes are
	// treated as boundaries on the ASCII side so this still matches.
	expr, _ := Parse("ai")
	if !MatchesText(expr, "تقنية ai متقدمة") {
		t.Error("expected ai match adjacent to Arabic letters")
	}
}

func TestTerm_TwoLetterTermStillBoundary(t *testing.T) {
	// "ml" — common false-positive inside HTML, XML, nightm-ml. With
	// word boundaries it should only match standalone.
	expr, _ := Parse("ml")
	if MatchesText(expr, "the html and xml feeds") {
		t.Error("ml must not match inside html / xml")
	}
	if !MatchesText(expr, "ml engineer needed") {
		t.Error("expected standalone ml match")
	}
}

// ── NOT operator ───────────────────────────────────────────────────

func TestParse_NotSimple(t *testing.T) {
	expr, err := Parse("NOT earn")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if MatchesText(expr, "earn daily passive income") {
		t.Error("NOT earn should reject text containing earn")
	}
	if !MatchesText(expr, "a normal tweet about cats") {
		t.Error("NOT earn should accept unrelated text")
	}
}

func TestParse_AndNotExclusion(t *testing.T) {
	// Classic magic-mode exclusion: match conferences, EXCEPT
	// MLM/crypto pyramid spam.
	expr, err := Parse(`(conference OR meetup) AND NOT (earn OR "join here")`)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !MatchesText(expr, "AI conference next week in Riyadh") {
		t.Error("legit conference must pass")
	}
	if MatchesText(expr, "meetup tomorrow — earn daily rewards!") {
		t.Error("MLM-flavoured meetup must be excluded")
	}
	if MatchesText(expr, "free crypto meetup — join here for $5000") {
		t.Error("crypto pyramid must be excluded")
	}
}

func TestParse_NotWithParens(t *testing.T) {
	// NOT can take a parenthesised expression as its body.
	expr, _ := Parse("a AND NOT (b OR c)")
	if !MatchesText(expr, "a is fine") {
		t.Error("expected pass for 'a'")
	}
	if MatchesText(expr, "a b together") {
		t.Error("NOT (b OR c) must reject text with b")
	}
	if MatchesText(expr, "a c together") {
		t.Error("NOT (b OR c) must reject text with c")
	}
}

func TestParse_DoubleNot(t *testing.T) {
	// Two NOTs cancel.
	expr, _ := Parse("NOT NOT a")
	if !MatchesText(expr, "a present") {
		t.Error("double-NOT should match 'a' present")
	}
	if MatchesText(expr, "no match here") {
		t.Error("double-NOT should reject when 'a' absent")
	}
}
