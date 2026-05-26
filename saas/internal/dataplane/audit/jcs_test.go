package audit_test

import (
	"encoding/json"
	"testing"

	"github.com/omarss/saas/internal/dataplane/audit"
)

// TestJCS_RFC8785_Vectors exercises the canonical-JSON wrapper against
// the RFC 8785 §3.4 reference vectors (shipped by gowebpki/jcs as
// testdata/). The cases are inlined here so the test does NOT depend on
// the module-cache layout — if the upstream library is ever swapped, an
// implementation that diverges from any single vector fails the build.
//
// Per ADR 012 the canonicalisation must produce byte-identical output
// across any future re-encode, otherwise hash-chain verification breaks.
// Adding a case here is acceptable; CHANGING a `want` value is a chain
// fork and requires an ADR update.
func TestJCS_RFC8785_Vectors(t *testing.T) {
	t.Parallel()
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{"null", `null`, `null`},
		{"true", `true`, `true`},
		{"false", `false`, `false`},
		{"simple_string", `"this is a test string 1235"`, `"this is a test string 1235"`},
		{
			// Per RFC 8785 §2.5 normalisation is out of scope — the
			// canonicaliser preserves code points verbatim. Both input
			// and expected use the JSON \u-escape form so the test is
			// stable across editors that NFC-normalise on save.
			"unicode_preserve",
			"{\"Unnormalized Unicode\":\"A\\u030a\"}",
			"{\"Unnormalized Unicode\":\"Å\"}",
		},
		{
			"french_keys",
			`{"peach":"This sorting order","péché":"is wrong according to French","pêche":"but canonicalization MUST","sin":"ignore locale"}`,
			`{"peach":"This sorting order","péché":"is wrong according to French","pêche":"but canonicalization MUST","sin":"ignore locale"}`,
		},
		{
			"arrays_numeric_key_ordering",
			`[56,{"d":true,"10":null,"1":[]}]`,
			`[56,{"1":[],"10":null,"d":true}]`,
		},
		{
			"structures",
			`{"1":{"f":{"f":"hi","F":5},"\n":56.0},"10":{},"":"empty","a":{},"111":[{"e":"yes","E":"no"}],"A":{}}`,
			`{"":"empty","1":{"\n":56,"f":{"F":5,"f":"hi"}},"10":{},"111":[{"E":"no","e":"yes"}],"A":{},"a":{}}`,
		},
		{
			// ECMAScript canonical number form: 333333333.33333329 -> 333333333.3333333
			// 1E30 -> 1e+30; 4.50 -> 4.5; 2e-3 -> 0.002; tiny -> 1e-27.
			"numbers_es6",
			`{"numbers":[333333333.33333329,1E30,4.50,2e-3,0.000000000000000000000000001]}`,
			`{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}`,
		},
		{
			"literals_array",
			`{"literals":[null,true,false]}`,
			`{"literals":[null,true,false]}`,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			got, err := audit.CanonicalBytes([]byte(tc.input))
			if err != nil {
				t.Fatalf("CanonicalBytes(%q): %v", tc.input, err)
			}
			if string(got) != tc.want {
				t.Errorf("canonical mismatch:\n want: %s\n got : %s", tc.want, got)
			}
		})
	}
}

// TestJCS_DeterministicOverRemarshals confirms two distinct map literals
// that happen to encode to the same canonical form do — the chain
// row_hash equality test depends on this.
func TestJCS_DeterministicOverRemarshals(t *testing.T) {
	t.Parallel()
	a := map[string]any{
		"action":    "tenant.create",
		"actor":     "user_abc",
		"resource":  "tenant_xyz",
		"timestamp": "2026-05-25T00:00:00Z",
	}
	b := map[string]any{
		"timestamp": "2026-05-25T00:00:00Z",
		"resource":  "tenant_xyz",
		"actor":     "user_abc",
		"action":    "tenant.create",
	}
	ca, err := audit.Canonical(a)
	if err != nil {
		t.Fatalf("Canonical(a): %v", err)
	}
	cb, err := audit.Canonical(b)
	if err != nil {
		t.Fatalf("Canonical(b): %v", err)
	}
	if string(ca) != string(cb) {
		t.Fatalf("non-deterministic canonical output:\n a: %s\n b: %s", ca, cb)
	}
}

// TestJCS_CanonicalAcceptsRawJSON makes sure callers that already hold a
// raw JSON envelope (e.g. outbox payload) get the same canonical bytes
// whether they pass the value or the bytes — the subscriber relies on
// CanonicalBytes for the outbox payload path.
func TestJCS_CanonicalAcceptsRawJSON(t *testing.T) {
	t.Parallel()
	v := map[string]any{"b": 2, "a": 1}
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	c1, err := audit.Canonical(v)
	if err != nil {
		t.Fatal(err)
	}
	c2, err := audit.CanonicalBytes(raw)
	if err != nil {
		t.Fatal(err)
	}
	if string(c1) != string(c2) {
		t.Fatalf("Canonical vs CanonicalBytes mismatch:\n via-value: %s\n via-bytes: %s", c1, c2)
	}
}
