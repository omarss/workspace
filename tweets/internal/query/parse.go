// Package query parses the free-text search expression `?q=` accepts:
// a small boolean mini-language with AND / OR, parens, and quoted
// "phrases". Built so the feed handler can express richer combinations
// (e.g. the "magic" preset) without needing multiple round-trips.
//
// Grammar (whitespace is insignificant except inside quotes):
//
//	expr   := orExpr
//	orExpr := andExpr ('OR' andExpr)*
//	andExpr:= unary ('AND'? unary)*
//	unary  := 'NOT' unary | term | '(' orExpr ')'
//	term   := WORD | PHRASE
//
// `NOT term` matches when term does NOT appear in the text. Useful in
// combination with AND/OR for surgical exclusion (e.g.
// `(tech AND event) AND NOT (earn OR "join here")` keeps the magic
// preset clear of pyramid-scheme spam).
//
// Backward-compat: a query without any operator (e.g. `foo bar`) is
// parsed as two terms in the implicit AND scope — same semantics as
// the previous "split-on-whitespace, AND every token" path.
//
// Matching is case-insensitive substring on the tweet body. Callers
// lowercase the body once and pass it to Matches() to avoid repeating
// the work for every term inside an expression.
package query

import (
	"errors"
	"fmt"
	"strings"
	"unicode"
)

// Expr is the parsed query tree. Matches returns true iff the given
// (already-lowercased) text satisfies the expression.
type Expr interface {
	Matches(textLower string) bool
}

// Always matches everything. Returned by Parse for an empty input so
// callers can use a uniform `expr.Matches(...)` without nil checks.
type Always struct{}

func (Always) Matches(string) bool { return true }

// Term is a single keyword. Value is always pre-lowercased.
//
// Matching is substring-based for terms containing any non-ASCII
// character (Arabic, etc.) — Unicode word boundaries are messy for
// scripts like Arabic where definite-article prefixes ("ال") attach
// to the noun, so substring is the pragmatic choice.
//
// For pure-ASCII-letter terms we require word boundaries instead, so
// the short keywords in the magic preset ("ai", "ml", "go") don't
// match inside unrelated words ("faith", "trample", "ego"). The
// boundary check looks at the rune immediately before / after the
// match and rejects when it's an ASCII letter or digit.
type Term struct{ Value string }

func (t Term) Matches(text string) bool {
	if t.Value == "" {
		return true
	}
	if isAsciiAlphaOrSpace(t.Value) {
		return containsWord(text, t.Value)
	}
	return strings.Contains(text, t.Value)
}

func isAsciiAlphaOrSpace(s string) bool {
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z':
		case r >= 'A' && r <= 'Z':
		case r == ' ' || r == '\t':
		default:
			return false
		}
	}
	return s != ""
}

// containsWord is strings.Contains with a word-boundary check on each
// side of the match. Operates on bytes (safe because the term is
// known to be pure ASCII when this is called).
//
// For each match at [at, end):
//   - leftOk: position `at` is 0, or the byte at `at-1` is not an
//     ASCII word char (a-z / A-Z / 0-9).
//   - rightOk: position `end` is len(text), or the byte at `end` is
//     not an ASCII word char.
//
// Multi-byte UTF-8 bytes (≥ 0x80) are never ASCII word chars under
// this definition, so a term sitting next to Arabic letters
// (e.g. "تقنية ai متقدمة" or "AIتطبيق") DOES match — Arabic and
// English are visually distinct boundaries.
func containsWord(text, term string) bool {
	if term == "" {
		return true
	}
	idx := 0
	for idx <= len(text)-len(term) {
		hit := strings.Index(text[idx:], term)
		if hit < 0 {
			return false
		}
		at := idx + hit
		end := at + len(term)
		leftOk := at == 0 || !isAsciiWordChar(text[at-1])
		rightOk := end == len(text) || !isAsciiWordChar(text[end])
		if leftOk && rightOk {
			return true
		}
		idx = at + 1
	}
	return false
}

func isAsciiWordChar(c byte) bool {
	if c >= 'a' && c <= 'z' {
		return true
	}
	if c >= 'A' && c <= 'Z' {
		return true
	}
	if c >= '0' && c <= '9' {
		return true
	}
	return false
}

// And matches when every child matches. Zero children is a vacuous
// truth — never produced by Parse, kept for safety.
type And struct{ Children []Expr }

func (a And) Matches(text string) bool {
	for _, c := range a.Children {
		if !c.Matches(text) {
			return false
		}
	}
	return true
}

// Or matches when any child matches. Zero children is vacuously false.
type Or struct{ Children []Expr }

func (o Or) Matches(text string) bool {
	for _, c := range o.Children {
		if c.Matches(text) {
			return true
		}
	}
	return false
}

// Not matches when the child does NOT match. Composes naturally with
// And/Or so `(a AND NOT b)` reads as "a and not b".
type Not struct{ Child Expr }

func (n Not) Matches(text string) bool {
	return !n.Child.Matches(text)
}

// Parse turns the raw query string into an Expr. Empty input returns
// Always — the caller doesn't have to special-case "no filter".
func Parse(input string) (Expr, error) {
	tokens, err := tokenize(input)
	if err != nil {
		return nil, err
	}
	if len(tokens) == 0 {
		return Always{}, nil
	}
	p := &parser{tokens: tokens}
	expr, err := p.parseOr()
	if err != nil {
		return nil, err
	}
	if p.pos < len(p.tokens) {
		return nil, fmt.Errorf("unexpected token %q at position %d", p.tokens[p.pos].value, p.pos)
	}
	return expr, nil
}

// ── Lexer ──────────────────────────────────────────────────────────

type tokenKind int

const (
	tkWord tokenKind = iota
	tkPhrase
	tkAnd
	tkOr
	tkNot
	tkLParen
	tkRParen
)

type token struct {
	kind  tokenKind
	value string // lower-cased; quotes stripped for phrases
}

func tokenize(input string) ([]token, error) {
	var out []token
	runes := []rune(input)
	i := 0
	for i < len(runes) {
		r := runes[i]
		switch {
		case unicode.IsSpace(r):
			i++
		case r == '(':
			out = append(out, token{kind: tkLParen, value: "("})
			i++
		case r == ')':
			out = append(out, token{kind: tkRParen, value: ")"})
			i++
		case r == '"':
			// Quoted phrase — preserves spaces verbatim.
			i++
			start := i
			for i < len(runes) && runes[i] != '"' {
				i++
			}
			if i >= len(runes) {
				return nil, errors.New("unterminated quoted phrase")
			}
			out = append(out, token{
				kind:  tkPhrase,
				value: strings.ToLower(string(runes[start:i])),
			})
			i++ // skip closing "
		default:
			// Bare word — runs until whitespace, paren, or quote.
			start := i
			for i < len(runes) && !unicode.IsSpace(runes[i]) &&
				runes[i] != '(' && runes[i] != ')' && runes[i] != '"' {
				i++
			}
			word := string(runes[start:i])
			lower := strings.ToLower(word)
			switch lower {
			case "and":
				out = append(out, token{kind: tkAnd, value: "AND"})
			case "or":
				out = append(out, token{kind: tkOr, value: "OR"})
			case "not":
				out = append(out, token{kind: tkNot, value: "NOT"})
			default:
				out = append(out, token{kind: tkWord, value: lower})
			}
		}
	}
	return out, nil
}

// ── Parser ─────────────────────────────────────────────────────────

type parser struct {
	tokens []token
	pos    int
}

func (p *parser) peek() (token, bool) {
	if p.pos >= len(p.tokens) {
		return token{}, false
	}
	return p.tokens[p.pos], true
}

func (p *parser) consume() token {
	t := p.tokens[p.pos]
	p.pos++
	return t
}

func (p *parser) parseOr() (Expr, error) {
	left, err := p.parseAnd()
	if err != nil {
		return nil, err
	}
	var children []Expr
	for {
		t, ok := p.peek()
		if !ok || t.kind != tkOr {
			break
		}
		p.consume()
		right, err := p.parseAnd()
		if err != nil {
			return nil, err
		}
		if len(children) == 0 {
			children = append(children, left)
		}
		children = append(children, right)
	}
	if len(children) == 0 {
		return left, nil
	}
	return Or{Children: children}, nil
}

func (p *parser) parseAnd() (Expr, error) {
	left, err := p.parseUnary()
	if err != nil {
		return nil, err
	}
	var children []Expr
	for {
		t, ok := p.peek()
		if !ok {
			break
		}
		// Stop at OR / RPAREN (handled by callers).
		if t.kind == tkOr || t.kind == tkRParen {
			break
		}
		// Explicit AND keyword is consumed; implicit AND is just the
		// presence of another term. NOT is the start of a new unary
		// (parsed below) — don't consume it here.
		if t.kind == tkAnd {
			p.consume()
		}
		right, err := p.parseUnary()
		if err != nil {
			return nil, err
		}
		if len(children) == 0 {
			children = append(children, left)
		}
		children = append(children, right)
	}
	if len(children) == 0 {
		return left, nil
	}
	return And{Children: children}, nil
}

func (p *parser) parseUnary() (Expr, error) {
	t, ok := p.peek()
	if !ok {
		return nil, errors.New("unexpected end of expression")
	}
	switch t.kind {
	case tkNot:
		p.consume()
		inner, err := p.parseUnary()
		if err != nil {
			return nil, err
		}
		return Not{Child: inner}, nil
	case tkLParen:
		p.consume()
		inner, err := p.parseOr()
		if err != nil {
			return nil, err
		}
		next, ok := p.peek()
		if !ok || next.kind != tkRParen {
			return nil, errors.New("missing closing parenthesis")
		}
		p.consume()
		return inner, nil
	case tkWord, tkPhrase:
		p.consume()
		return Term{Value: t.value}, nil
	case tkAnd, tkOr:
		return nil, fmt.Errorf("unexpected operator %q (expected term)", t.value)
	case tkRParen:
		return nil, errors.New("unexpected closing parenthesis")
	}
	return nil, fmt.Errorf("unexpected token %q", t.value)
}

// MatchesText is a convenience for "lowercase once, evaluate expr".
// Callers that match many tweets against the same expression should
// inline the lowercase step themselves to amortise the allocation.
func MatchesText(e Expr, text string) bool {
	return e.Matches(strings.ToLower(text))
}
