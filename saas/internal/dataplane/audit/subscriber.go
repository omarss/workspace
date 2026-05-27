package audit

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
)

// Subscriber consumes the outbox dispatcher's events and writes the
// §18.3-audited subset into audit_event. It is wired into the data-plane
// binary via outbox.Publisher composition (see cmd/dataplane/main.go).
//
// Idempotency: every outbox event carries an immutable event_id (ULID).
// The repository's UNIQUE INDEX on source_event_id ensures at-most-one
// audit row per outbox event even when the outbox dispatcher
// re-delivers after a transient publish failure.
type Subscriber struct {
	repo Repository
	log  *slog.Logger
}

// NewSubscriber builds a Subscriber over repo. log may be nil.
func NewSubscriber(repo Repository, log *slog.Logger) *Subscriber {
	if log == nil {
		log = slog.Default()
	}
	return &Subscriber{repo: repo, log: log}
}

// AuditedEventTypes is the resolved §18.3 list of outbox event types
// that produce an audit_event row. Exported so the cmd-level wiring can
// assert against it; new audit-eligible events MUST be added here AND
// in AGENTS.md §18.3 in the same PR.
var AuditedEventTypes = map[string]string{
	// Tenants
	"tenant.created":   "tenant.create",
	"tenant.updated":   "tenant.update",
	"tenant.suspended": "tenant.suspend",
	"tenant.deleted":   "tenant.delete",
	// Identity
	"user.created":                  "user.create",
	"user.disabled":                 "user.disable",
	"user.enabled":                  "user.enable",
	"user.email_verified":           "user.email_verify",
	"user.password_reset_requested": "user.password_reset_request",
	"user.social_linked":            "user.social_link",
	"user.social_unlinked":          "user.social_unlink",
	// Organizations / Members / Invitations
	"member.invited":      "member.invite",
	"member.joined":       "member.join",
	"member.removed":      "member.remove",
	"member.role_changed": "member.role_change",
	// RBAC
	"role.created":           "role.create",
	"role.updated":           "role.update",
	"role.deleted":           "role.delete",
	"member_role.assigned":   "member_role.assign",
	"member_role.unassigned": "member_role.unassign",
	"permission.granted":     "permission.grant",
	"permission.revoked":     "permission.revoke",
	"authorization.denied":   "authorization.deny",
	// API keys
	"api_key.created": "api_key.create",
	"api_key.rotated": "api_key.rotate",
	"api_key.revoked": "api_key.revoke",
	// Notifications (channel CRUD is audited; per-message sends are
	// noisy and excluded — only failures audit, per §18.3 list).
	"notification.delivery_failed": "notification.delivery_fail",
	"notification_channel.created": "notification_channel.create",
	"notification_channel.rotated": "notification_channel.rotate",
	"notification_channel.deleted": "notification_channel.delete",
	// Operator / Control plane events (consumed once Phase 11+ emits them;
	// keys exist here so audit-eligibility is centralised in one map).
	"operator.login":                 "operator.login",
	"operator.impersonation_started": "operator.impersonation_start",
	"operator.impersonation_ended":   "operator.impersonation_end",
	"deployment.provisioned":         "deployment.provision",
	"deployment.upgraded":            "deployment.upgrade",
	"deployment.rollback":            "deployment.rollback",
	"deployment.destroyed":           "deployment.destroy",
	"deployment.purged":              "deployment.purge",
	"deployment.domain_attached":     "deployment.domain_attach",
	"deployment.domain_verified":     "deployment.domain_verify",
	"deployment.domain_detached":     "deployment.domain_detach",
}

// IsAudited reports whether eventType produces an audit_event row.
func IsAudited(eventType string) bool {
	_, ok := AuditedEventTypes[eventType]
	return ok
}

// Handle is the per-event entry point. The outbox dispatcher invokes it
// for every event; non-audited types short-circuit early. The function
// is tolerant: a failure inserting an audit row logs at error level but
// does not bubble up — the outbox row should still be marked published
// to avoid an unbounded retry loop on a malformed audit insert. The
// Phase 13 SIEM hook will catch persistent audit-write failures via
// metrics.
func (s *Subscriber) Handle(ctx context.Context, e db.OutboxEvent) error {
	action, ok := AuditedEventTypes[e.Type]
	if !ok {
		return nil
	}
	if e.TenantID == nil || *e.TenantID == "" {
		// Tenant-less audit-eligible events (e.g. operator.login) are a
		// Phase 11+ control-plane concern; the data-plane audit table
		// requires a tenant_id, so we skip with a warning. Phase 13 may
		// promote a "deployment-level audit" table for these.
		s.log.Warn("audit subscriber: skipping tenantless audited event",
			"type", e.Type, "event_id", e.EventID)
		return nil
	}
	payload := decodePayload(e.Payload)
	in := payloadToInput(action, *e.TenantID, e.EventID, e.OccurredAt.Time, payload)
	if _, err := s.repo.Append(ctx, in); err != nil {
		if errors.Is(err, ErrInvalidInput) {
			s.log.Warn("audit subscriber: dropping invalid event",
				"type", e.Type, "event_id", e.EventID, "err", err)
			return nil
		}
		s.log.Error("audit subscriber: append failed",
			"type", e.Type, "event_id", e.EventID, "err", err)
		// Returning the error keeps the outbox row retriable; the
		// dispatcher will increment delivery_attempts and try again.
		return fmt.Errorf("audit subscriber: append: %w", err)
	}
	return nil
}

// payloadToInput maps an outbox payload to a NewEventInput. The mapping
// is intentionally tolerant: missing fields fall back to "system"
// actor so an event mid-development cannot block the dispatcher.
func payloadToInput(action, tenantID, sourceEventID string, occurredAt time.Time, payload map[string]any) NewEventInput {
	actorType := lookupString(payload, "actor_type", "system")
	if !validActorType(actorType) {
		actorType = "system"
	}
	resourceType, resourceID := inferResource(action, payload)
	in := NewEventInput{
		TenantID:      tenantID,
		ActorType:     ActorType(actorType),
		ActorID:       lookupString(payload, "actor_id", "system"),
		Action:        action,
		ResourceType:  resourceType,
		ResourceID:    resourceID,
		OccurredAt:    occurredAt,
		IPAddress:     lookupString(payload, "ip_address", ""),
		UserAgent:     lookupString(payload, "user_agent", ""),
		RequestID:     lookupString(payload, "request_id", ""),
		Metadata:      stripPII(extractMetadata(payload)),
		SourceEventID: sourceEventID,
	}
	return in
}

// inferResource derives resource_type / resource_id from the event
// action prefix (the part before the dot) and well-known payload keys.
// Falls back to empty strings — the repository's validateNewEvent
// rejects rows missing resource_type so the subscriber logs and skips
// rather than poisoning the chain.
func inferResource(action string, payload map[string]any) (string, string) {
	resourceType := ""
	if i := strings.IndexByte(action, '.'); i > 0 {
		resourceType = action[:i]
	}
	// Look for the obvious id key — e.g. tenant_id for a tenant.*
	// event. If the event explicitly carries resource_type/resource_id
	// we honour those over the inferred values.
	if v, ok := payload["resource_type"]; ok {
		if s, ok := v.(string); ok && s != "" {
			resourceType = s
		}
	}
	resourceID := lookupString(payload, "resource_id", "")
	if resourceID == "" && resourceType != "" {
		// Try `<type>_id` then `id` as best-effort fallbacks.
		resourceID = lookupString(payload, resourceType+"_id", "")
		if resourceID == "" {
			resourceID = lookupString(payload, "id", "")
		}
	}
	return resourceType, resourceID
}

func decodePayload(raw []byte) map[string]any {
	if len(raw) == 0 {
		return map[string]any{}
	}
	var m map[string]any
	if err := json.Unmarshal(raw, &m); err != nil {
		return map[string]any{}
	}
	return m
}

// extractMetadata returns the event payload minus the well-known
// envelope fields. Subscribers may opt to namespace their custom
// metadata under a `metadata` key; if present we use that, otherwise we
// strip the known fields and pass the rest through.
func extractMetadata(payload map[string]any) map[string]any {
	if m, ok := payload["metadata"].(map[string]any); ok {
		return m
	}
	skip := map[string]struct{}{
		"actor_type": {}, "actor_id": {}, "tenant_id": {},
		"resource_type": {}, "resource_id": {},
		"ip_address": {}, "user_agent": {}, "request_id": {},
	}
	out := make(map[string]any, len(payload))
	for k, v := range payload {
		if _, drop := skip[k]; drop {
			continue
		}
		out[k] = v
	}
	return out
}

func lookupString(m map[string]any, key, def string) string {
	if v, ok := m[key]; ok {
		if s, ok := v.(string); ok && s != "" {
			return s
		}
	}
	return def
}

func validActorType(s string) bool {
	switch ActorType(s) {
	case ActorUser, ActorAPIKey, ActorOperator, ActorOperatorImpersonation, ActorSystem:
		return true
	}
	return false
}
