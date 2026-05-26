// Package workflows bundles the §21 first-class flows on top of the
// generated controlplane and dataplane clients. Each workflow is a free
// function that takes the relevant client as its first argument.
//
// Error policy: every workflow returns a *APIError when the server responds
// with a non-2xx status. The caller can use errors.As to inspect the
// problem-type discriminator (RFC 9457 type URI) — that's the stable error
// identity, not the HTTP status. The SDK does NOT auto-retry on 5xx
// (anti-pattern guard); the consumer chooses backoff.
package workflows

import (
	"encoding/json"
	"fmt"
	"net/http"
)

// APIError wraps an RFC 9457 problem-details payload returned by either
// plane. The Type field is the stable discriminator (e.g. "https://
// saas.omarss.net/problems/validation-error"); switch on it at the call
// site rather than HTTP status because the platform may map the same
// problem to different statuses across versions.
type APIError struct {
	// StatusCode is the HTTP status returned by the server.
	StatusCode int
	// Type is the RFC 9457 problem-type URI (the stable discriminator).
	// Empty if the response was not a problem+json payload.
	Type string
	// Title is the human-readable problem summary.
	Title string
	// Detail is an optional longer description of the specific occurrence.
	Detail string
	// Instance is the URI of the specific occurrence.
	Instance string
	// RequestID echoes the platform request id, when present, for tracing.
	RequestID string
	// Raw is the verbatim response body, useful for debugging when the
	// server returns a non-problem+json body (e.g. plain text 502).
	Raw []byte
}

// Error implements the error interface. Format: "<status> <title>: <detail>".
func (e *APIError) Error() string {
	if e == nil {
		return "<nil APIError>"
	}
	if e.Detail != "" {
		return fmt.Sprintf("%d %s: %s", e.StatusCode, e.Title, e.Detail)
	}
	if e.Title != "" {
		return fmt.Sprintf("%d %s", e.StatusCode, e.Title)
	}
	return fmt.Sprintf("%d <unknown problem>", e.StatusCode)
}

// IsType returns true iff the error is an APIError with the given
// problem-type URI. Use to branch on specific problem categories.
func IsType(err error, problemType string) bool {
	if err == nil {
		return false
	}
	apiErr, ok := err.(*APIError)
	if !ok {
		return false
	}
	return apiErr.Type == problemType
}

// parseProblem builds an APIError from a non-2xx HTTP response body and
// status code. The body is assumed to be RFC 9457 problem+json; if parsing
// fails the raw bytes are preserved and the title falls back to the HTTP
// status text.
func parseProblem(statusCode int, body []byte) *APIError {
	apiErr := &APIError{StatusCode: statusCode, Raw: body}
	// Mirror of dataplane.Problem / controlplane has no Problem schema so
	// we accept either shape (control plane omits some optional fields).
	var p struct {
		Type      string `json:"type"`
		Title     string `json:"title"`
		Detail    string `json:"detail"`
		Instance  string `json:"instance"`
		RequestID string `json:"request_id"`
	}
	if err := json.Unmarshal(body, &p); err == nil {
		apiErr.Type = p.Type
		apiErr.Title = p.Title
		apiErr.Detail = p.Detail
		apiErr.Instance = p.Instance
		apiErr.RequestID = p.RequestID
	}
	if apiErr.Title == "" {
		apiErr.Title = http.StatusText(statusCode)
	}
	return apiErr
}
