package audit

import (
	"bytes"
	"context"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
	platformlog "github.com/omarss/saas/internal/platform/log"
)

// Service is the Phase 10 audit application service.
//
// Per CONVENTIONS.md §2, every tenant-bound method takes
// (ctx, tenantID, ...). AssertTenant precedes any tenant-bound read or
// write — read endpoints rely on AssertTenant alone for MVP; the
// `audit.read` permission gating lands with the v1 RBAC hardening pass
// (see CONVENTIONS.md §11 + ADR 012).
//
// The Append verb is NOT exposed on the service surface deliberately:
// new audit rows enter the table only via the outbox subscriber so the
// §18.3 list stays the single source of truth for what gets audited.
// Service methods are read-only.
type Service struct {
	repo Repository
}

// NewService constructs a Service over repo.
func NewService(repo Repository) *Service {
	return &Service{repo: repo}
}

// Get returns a single audit event by id.
func (s *Service) Get(ctx context.Context, tenantID, eventID string) (Event, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Event{}, err
	}
	return s.repo.Get(ctx, tenantID, eventID)
}

// List returns up to filter.Limit rows matching filter. The caller-side
// tenant_id is taken from the URL; AssertTenant rejects cross-tenant
// reads.
func (s *Service) List(ctx context.Context, filter ListFilter) ([]Event, bool, error) {
	if err := auth.AssertTenant(ctx, filter.TenantID); err != nil {
		return nil, false, err
	}
	if filter.Limit <= 0 {
		filter.Limit = 25
	}
	if filter.Limit > 200 {
		filter.Limit = 200
	}
	return s.repo.List(ctx, filter)
}

// ExportSyncBudget is the inline-response size budget for sync exports.
// Heuristic; the export handler trips ErrExportTooLarge when the
// candidate result would exceed this. Async export wiring lands in v1
// (per Phase 10 plan §10.9).
const ExportSyncBudget = 1 << 20 // 1 MiB

// Export materialises the filtered rows into either JSON or CSV bytes.
// Returns ErrExportTooLarge when the output exceeds ExportSyncBudget so
// the handler can convert into a 413 / 202 hand-off.
func (s *Service) Export(ctx context.Context, filter ListFilter, format ExportFormat) ([]byte, string, error) {
	if err := auth.AssertTenant(ctx, filter.TenantID); err != nil {
		return nil, "", err
	}
	// Cap at the largest sane page so we never load > 10k rows even
	// when callers request more; the export endpoint is bounded by
	// ExportSyncBudget anyway.
	if filter.Limit <= 0 || filter.Limit > 10000 {
		filter.Limit = 10000
	}
	events, _, err := s.repo.List(ctx, filter)
	if err != nil {
		return nil, "", err
	}
	switch format {
	case ExportFormatCSV:
		buf, err := encodeCSV(events)
		if err != nil {
			return nil, "", err
		}
		if buf.Len() > ExportSyncBudget {
			return nil, "", ErrExportTooLarge
		}
		return buf.Bytes(), "text/csv", nil
	case ExportFormatJSON, "":
		body, err := json.Marshal(map[string]any{"data": eventsToExport(events)})
		if err != nil {
			return nil, "", fmt.Errorf("audit: export json: %w", err)
		}
		if len(body) > ExportSyncBudget {
			return nil, "", ErrExportTooLarge
		}
		return body, "application/json", nil
	default:
		return nil, "", fmt.Errorf("%w: unsupported export format %q", ErrInvalidInput, format)
	}
}

// VerifyChain walks the audit chain (optionally scoped to tenantFilter)
// and returns the integrity result. Operator-only — the data-plane HTTP
// surface does NOT expose this; the control-plane handler in Phase 11
// will. Surfacing the chain-walker here keeps Phase 10 self-contained:
// the control-plane wiring is a thin pass-through to this function.
func (s *Service) VerifyChain(ctx context.Context, tenantFilter string) (IntegrityResult, error) {
	return VerifyChain(ctx, s.repo, tenantFilter, time.Now)
}

// encodeCSV writes events as CSV. Columns mirror the JSON shape for
// downstream tools.
func encodeCSV(events []Event) (*bytes.Buffer, error) {
	buf := &bytes.Buffer{}
	w := csv.NewWriter(buf)
	header := []string{
		"id", "tenant_id", "actor_type", "actor_id", "action",
		"resource_type", "resource_id", "occurred_at",
		"ip_address", "user_agent", "request_id",
		"prev_hash", "row_hash", "chain_sequence",
	}
	if err := w.Write(header); err != nil {
		return nil, fmt.Errorf("audit: csv header: %w", err)
	}
	for _, e := range events {
		if err := w.Write([]string{
			e.ID, e.TenantID, string(e.ActorType), e.ActorID, e.Action,
			e.ResourceType, e.ResourceID, e.OccurredAt.UTC().Format(time.RFC3339Nano),
			e.IPAddress, e.UserAgent, e.RequestID,
			HexHash(e.PrevHash), HexHash(e.RowHash), fmt.Sprintf("%d", e.ChainSequence),
		}); err != nil {
			return nil, fmt.Errorf("audit: csv row: %w", err)
		}
	}
	w.Flush()
	if err := w.Error(); err != nil {
		return nil, err
	}
	return buf, nil
}

// eventsToExport converts in-memory Events to the wire shape used by
// the JSON export.
func eventsToExport(events []Event) []map[string]any {
	out := make([]map[string]any, 0, len(events))
	for _, e := range events {
		out = append(out, eventToWire(e))
	}
	return out
}

// eventToWire is the shared marshal helper between Export and the read
// handlers. Keeping the shape in one place ensures the chain-relevant
// fields appear identically across endpoints.
func eventToWire(e Event) map[string]any {
	return map[string]any{
		"id":             e.ID,
		"tenant_id":      e.TenantID,
		"actor_type":     string(e.ActorType),
		"actor_id":       e.ActorID,
		"action":         e.Action,
		"resource_type":  e.ResourceType,
		"resource_id":    nullableString(e.ResourceID),
		"occurred_at":    e.OccurredAt.UTC().Format(time.RFC3339Nano),
		"ip_address":     nullableString(e.IPAddress),
		"user_agent":     nullableString(e.UserAgent),
		"request_id":     nullableString(e.RequestID),
		"metadata":       e.Metadata,
		"prev_hash":      HexHash(e.PrevHash),
		"row_hash":       HexHash(e.RowHash),
		"chain_sequence": e.ChainSequence,
	}
}

// nullableString returns nil for an empty string so JSON renders `null`
// instead of `""` — matches the OpenAPI shape which marks PII fields as
// `[string, "null"]`.
func nullableString(s string) any {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	return s
}

// stripPII removes top-level keys from m that match the platform's
// static redactor list. Nested objects are walked recursively so PII
// hidden one level deep is still redacted. This keeps Phase 5's PII
// invariant intact when subscribers forward identity-bearing event
// payloads into audit_event.metadata.
func stripPII(m map[string]any) map[string]any {
	if m == nil {
		return map[string]any{}
	}
	out := make(map[string]any, len(m))
	for k, v := range m {
		if platformlog.IsRedactedKey(k) {
			out[k] = "[REDACTED]"
			continue
		}
		switch vv := v.(type) {
		case map[string]any:
			out[k] = stripPII(vv)
		case []any:
			out[k] = stripPIISlice(vv)
		default:
			out[k] = v
		}
	}
	return out
}

func stripPIISlice(arr []any) []any {
	out := make([]any, len(arr))
	for i, v := range arr {
		if m, ok := v.(map[string]any); ok {
			out[i] = stripPII(m)
			continue
		}
		out[i] = v
	}
	return out
}
