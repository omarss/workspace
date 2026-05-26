package audit

import "time"

// ActorType mirrors auth.ActorType. We re-declare it as a string-typed
// enum on the domain side so this package does not import the platform
// auth package outside the handler boundary — keeps the dep graph
// one-way (handlers translate principal → actor type).
type ActorType string

// ActorType values stored verbatim in the audit_event.actor_type column.
// The CHECK constraint in migrations/dataplane/000008_audit.up.sql pins
// these strings — adding a new actor type requires a migration update.
const (
	ActorUser                  ActorType = "user"
	ActorAPIKey                ActorType = "api_key"
	ActorOperator              ActorType = "operator"
	ActorOperatorImpersonation ActorType = "operator_impersonation"
	ActorSystem                ActorType = "system"
)

// Event is the in-memory representation of a row in the audit_event
// table. Returned by reads; assembled by the subscriber for inserts.
//
// The hash columns are present on the struct so the verifier can stream
// rows without a second round-trip. Service-level consumers should treat
// PrevHash + RowHash as opaque — they are bytes, not text.
type Event struct {
	ID            string
	TenantID      string
	ActorType     ActorType
	ActorID       string
	Action        string
	ResourceType  string
	ResourceID    string
	OccurredAt    time.Time
	IPAddress     string
	UserAgent     string
	RequestID     string
	Metadata      map[string]any
	SourceEventID string
	PrevHash      []byte
	RowHash       []byte
	ChainSequence int64
}

// NewEventInput carries the subscriber-supplied fields needed to mint a
// new row. The repository fills ID, OccurredAt (when zero),
// ChainSequence, PrevHash, and RowHash.
type NewEventInput struct {
	TenantID      string
	ActorType     ActorType
	ActorID       string
	Action        string
	ResourceType  string
	ResourceID    string
	OccurredAt    time.Time
	IPAddress     string
	UserAgent     string
	RequestID     string
	Metadata      map[string]any
	SourceEventID string
}

// CanonicalBody returns the map representation hashed into row_hash.
// CRITICAL: changing this shape changes every existing row's expected
// hash — see ADR 012 §Consequences. Adding a NEW field is acceptable as
// long as the old fields stay in the same canonical positions; JCS
// sorts keys alphabetically so insertion order is irrelevant.
func (e Event) CanonicalBody() map[string]any {
	body := map[string]any{
		"id":            e.ID,
		"tenant_id":     e.TenantID,
		"actor_type":    string(e.ActorType),
		"actor_id":      e.ActorID,
		"action":        e.Action,
		"resource_type": e.ResourceType,
		"resource_id":   e.ResourceID,
		"occurred_at":   e.OccurredAt.UTC().Format(time.RFC3339Nano),
		"ip_address":    e.IPAddress,
		"user_agent":    e.UserAgent,
		"request_id":    e.RequestID,
		"metadata":      e.Metadata,
	}
	if e.SourceEventID != "" {
		body["source_event_id"] = e.SourceEventID
	}
	return body
}

// ListFilter narrows the list endpoint. Zero-value fields are wildcards.
type ListFilter struct {
	TenantID     string
	Action       string
	ResourceType string
	ResourceID   string
	ActorID      string
	OccurredFrom time.Time
	OccurredTo   time.Time
	Limit        int
}

// ExportFormat enumerates the export endpoint output shapes.
type ExportFormat string

// ExportFormat values.
const (
	ExportFormatJSON ExportFormat = "json"
	ExportFormatCSV  ExportFormat = "csv"
)

// ExportJob represents an asynchronous export request. MVP keeps the
// status synchronous (sized in-memory) but the type is shaped so a
// background worker can adopt it without an API break.
type ExportJob struct {
	ID         string
	TenantID   string
	Format     ExportFormat
	Filter     ListFilter
	Status     ExportStatus
	URL        string
	CreatedAt  time.Time
	FinishedAt time.Time
}

// ExportStatus enumerates job lifecycle states.
type ExportStatus string

// ExportStatus values.
const (
	ExportPending  ExportStatus = "pending"
	ExportRunning  ExportStatus = "running"
	ExportComplete ExportStatus = "complete"
	ExportFailed   ExportStatus = "failed"
)
