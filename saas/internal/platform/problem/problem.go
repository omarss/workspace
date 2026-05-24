// Package problem produces RFC 9457 Problem Details responses. Every error
// surfaced from a handler goes through here so the platform never invents
// ad-hoc error shapes (AGENTS.md section 5.5).
package problem

// TypeURI base for platform-specific problem types. Catalogue per type lives in
// openapi/problems/ — Phase 3 promotes this into a shared component.
const TypeURI = "https://saas.omarss.net/problems/"

// Problem matches the openapi Problem schema. The handler package re-uses the
// generated dataplaneapi.Problem; this is the canonical helper builder.
type Problem struct {
	Type      string       `json:"type"`
	Title     string       `json:"title"`
	Status    int          `json:"status"`
	Detail    string       `json:"detail,omitempty"`
	Instance  string       `json:"instance,omitempty"`
	RequestID string       `json:"request_id,omitempty"`
	Errors    []FieldError `json:"errors,omitempty"`
}

// FieldError records a single field-scoped validation issue.
type FieldError struct {
	Field   string `json:"field"`
	Message string `json:"message"`
	Code    string `json:"code,omitempty"`
}

// New constructs a Problem with the platform's type URI prefix.
func New(slug, title string, status int, detail, instance string) Problem {
	return Problem{
		Type:     TypeURI + slug,
		Title:    title,
		Status:   status,
		Detail:   detail,
		Instance: instance,
	}
}
