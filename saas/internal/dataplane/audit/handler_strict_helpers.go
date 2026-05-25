package audit

import (
	"bytes"
	"encoding/json"
	"io"

	httpapi "github.com/omarss/saas/internal/dataplane/httpapi"
)

// newProblem builds the typed httpapi.Problem used by the StrictServer
// error responses. Keeping construction in one place avoids per-response
// boilerplate.
func newProblem(status int, typeURI, title, detail, instance string) httpapi.Problem {
	p := httpapi.Problem{
		Type:   typeURI,
		Title:  title,
		Status: status,
	}
	if detail != "" {
		p.Detail = &detail
	}
	if instance != "" {
		p.Instance = &instance
	}
	return p
}

// bytesReader returns an io.Reader over b. Used for the CSV export
// response which the codegen models as an io.Reader.
func bytesReader(b []byte) io.Reader {
	return bytes.NewReader(b)
}

// unmarshalAuditList parses a JSON export blob into the typed
// AuditEventListResponse used by the 200 JSON branch of the export.
func unmarshalAuditList(b []byte, out *httpapi.AuditEventListResponse) error {
	// The service-side Export wraps rows as `{"data": [...]}` without a
	// pagination envelope — we decode into a permissive intermediate.
	var raw struct {
		Data []httpapi.AuditEvent `json:"data"`
	}
	if err := json.Unmarshal(b, &raw); err != nil {
		return err
	}
	out.Data = raw.Data
	out.Pagination = httpapi.Pagination{HasMore: false}
	return nil
}
