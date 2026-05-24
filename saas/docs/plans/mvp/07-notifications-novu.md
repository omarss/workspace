# Phase 6 — Notifications Module (Novu Wrapper) + BYOK Vendor Creds

> **Goal**: Ship the Notifications module wrapping Novu (v3.15.0, self-hosted). Add `/v1/notification-channels`, `/v1/notifications/send`, `/v1/notifications/{id}`, `/v1/notification-workflows` endpoints. Land the 7-container Novu stack in `compose.yaml` (mongodb + redis + novu-api + novu-worker + novu-ws + novu-dashboard). Implement BYOK: each Notification Channel stores Deployment-provided SMTP/SendGrid/SES creds, envelope-encrypted via the Phase 4 helper. Rewire Identity (Phase 5) password-reset email to flow through Notifications instead of Keycloak's built-in SMTP.
>
> **Why now**: Per scope-change ADR 013 (00-master.md), Notifications is MVP. Phase 7 Organizations depends on Notifications for invitation emails — must land first. Phase 10 Audit depends on Notifications for the §18.3 list. The 9-checkpoint policy gates here (CHECKPOINT 2) because misdesigning BYOK leaks vendor secrets at every channel read.
>
> **What this phase does NOT do**: No SMS / WhatsApp / push channels — explicitly v1 roadmap (00-master.md §"Scope changes" — only email + in-app are MVP). No newsletter / broadcast flow (v1 roadmap). No analytics / open-rate tracking (out of MVP). No template authoring UI of our own (operators use Novu's `dashboard` container at port 4000 for now).
>
> **Maps to AGENTS.md**: §4.4 (Novu approved), §8.7.3 + the Phase 6 scope-change override (Notifications now MVP), §18.3 (audit list: notification send), §18.7 (BYOK envelope encryption + rotation API + audit), §21 (first-class workflow: send-notification). `01-foundations.md` §5 (envelope) and §11 (idempotency on send).
>
> **Estimated subagent sessions**: 3 (one for compose + Novu bring-up + OpenAPI; one for module impl + BYOK channel encryption; one for Identity rewire + tests).

---

## Pre-flight

1. AGENTS.md §4.4, §8.7.3, §18.3, §18.7, §21.
2. 00-master.md scope-change row for Notifications (ADR 013) and BYOK (ADR 017).
3. CONVENTIONS.md (Phase 3 + Phase 4 + Phase 5 updates).
4. `01-foundations.md` §5 (envelope encryption) — every channel credential field uses the persist walker.
5. Phase 4 (`05-openbao-integration.md`) — confirm envelope client healthy.
6. Phase 5 (`06-identity-keycloak.md`) — Identity emits a `user.password_reset_requested` outbox event that Phase 6 will consume.
7. Novu image pin (resolved pre-Phase-6): **`ghcr.io/novuhq/novu/<service>:3.15.0`** (Apache-2.0). Novu's current major is v3.x; v0.24.x and v1.x/v2.x are legacy and not selected. No separate LTS branch exists — Novu rolls forward on v3 minors with low self-hoster breakage between 3.13 → 3.15. New required env in v3.x: `NOVU_SECRET_KEY` (alongside `JWT_SECRET` and the exactly-32-char `STORE_ENCRYPTION_KEY`). The historical `novu/web` container is gone — replaced by `novu/dashboard` on port 4000. Re-verify on GHCR (`https://github.com/novuhq/novu/pkgs/container/novu%2Fapi`) at execution time and bump if a stable `3.16.x` exists.

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Novu version pin | `ghcr.io/novuhq/novu/<service>:3.15.0` (resolved) | `3.16.x` if published before execution; legacy 0.24.x rejected |
| Channels in MVP | `email`, `in_app` | `sms`, `push`, `chat`, `whatsapp` (v1 roadmap) |
| Email provider BYOK options in MVP | SMTP (RFC 5321), SendGrid HTTP, AWS SES HTTP | Mailgun, Postmark, Resend (v1) |
| Channel credential storage | Envelope-encrypted via Phase 4 walker; persisted as columns in `notification_channel` | OpenBao KV (refused — adds round-trip per send; channel rows are hot read path) |
| Send queue | Novu's internal queue (redis-backed) — platform delegates queueing | Our own asynq queue (refused — duplicates Novu's role) |
| Workflow definitions | Stored in Novu (the Novu admin UI authors templates); platform stores `(name, novu_workflow_id)` mapping | Stored in platform DB (refused — re-invents Novu) |
| Idempotency on send | Required (POST /v1/notifications/send) | Optional (refused — high volume + retry storms) |
| BYOK rotation API | `POST /v1/notification-channels/{id}/rotate-credentials` returns the new creds once + emits audit | Update via PATCH (refused — Stripe pattern: rotation is a distinct verb) |
| Audit on credential read | Yes — every read goes through `audit_event` (Phase 10) | No (refused — §18.7 mandates audit on every key access) |

If the user disagrees on any default, stop. BYOK choices propagate to every channel type.

---

## Tasks

### 6.1 Add Novu stack to `compose.yaml`

```yaml
  mongodb:
    image: mongo:7
    environment:
      MONGO_INITDB_ROOT_USERNAME: novu
      MONGO_INITDB_ROOT_PASSWORD: novu-dev
    volumes: ["novu-mongo:/data/db"]
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 3s
      timeout: 2s
      retries: 30

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 3s

  novu-api:
    image: ghcr.io/novuhq/novu/api:3.15.0
    depends_on:
      mongodb: { condition: service_healthy }
      redis:   { condition: service_healthy }
    environment:
      NODE_ENV: production
      PORT: 3000
      MONGO_URL: "mongodb://novu:novu-dev@mongodb:27017/novu-db?authSource=admin"
      REDIS_HOST: redis
      REDIS_PORT: 6379
      JWT_SECRET: "dev-novu-jwt-secret-32-bytes-hex!!"   # openssl rand -hex 32 in prod
      STORE_ENCRYPTION_KEY: "dev-store-key-exactly-32-c!!"  # MUST be exactly 32 chars; openssl rand -hex 16
      NOVU_SECRET_KEY: "dev-novu-secret-key-32-bytes!!"  # new in v3.x; openssl rand -hex 32
      IS_SELF_HOSTED: "true"
      IS_V2_ENABLED: "true"
      MONGO_AUTO_CREATE_INDEXES: "true"
      API_ROOT_URL: "http://localhost:3000"
      FRONT_BASE_URL: "http://localhost:4000"
    ports: ["3000:3000"]
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:3000/v1/health-check"]
      interval: 5s
      retries: 30

  novu-worker:
    image: ghcr.io/novuhq/novu/worker:3.15.0
    depends_on:
      mongodb: { condition: service_healthy }
      redis:   { condition: service_healthy }
    environment:
      NODE_ENV: production
      PORT: 3004
      MONGO_URL: "mongodb://novu:novu-dev@mongodb:27017/novu-db?authSource=admin"
      REDIS_HOST: redis
      REDIS_PORT: 6379
      STORE_ENCRYPTION_KEY: "dev-store-key-exactly-32-c!!"
      API_ROOT_URL: http://novu-api:3000
      BROADCAST_QUEUE_CHUNK_SIZE: "100"
      MULTICAST_QUEUE_CHUNK_SIZE: "100"

  novu-ws:
    image: ghcr.io/novuhq/novu/ws:3.15.0
    depends_on:
      mongodb: { condition: service_healthy }
      redis:   { condition: service_healthy }
    environment:
      NODE_ENV: production
      PORT: 3002
      MONGO_URL: "mongodb://novu:novu-dev@mongodb:27017/novu-db?authSource=admin"
      REDIS_HOST: redis
      REDIS_PORT: 6379
      JWT_SECRET: "dev-novu-jwt-secret-32-bytes-hex!!"
    ports: ["3002:3002"]

  novu-dashboard:
    image: ghcr.io/novuhq/novu/dashboard:3.15.0
    depends_on:
      novu-api: { condition: service_healthy }
    environment:
      VITE_API_HOSTNAME: "http://localhost:3000"
      VITE_WEBSOCKET_HOSTNAME: "http://localhost:3002"
    ports: ["4000:4000"]

volumes:
  novu-mongo: {}
```

**Note**: The `JWT_SECRET` + `STORE_ENCRYPTION_KEY` are dev sentinel strings. Production deployments load them from OpenBao KV at startup (Phase 12e wires this into the per-Deployment provisioning sequence — but for Phase 6 local dev, hardcoded is acceptable). Document in compose.yaml comments.

### 6.2 Make targets

```make
.PHONY: novu-up novu-down novu-logs novu-bootstrap

novu-up:
	docker compose -f compose.yaml up -d --wait mongodb redis novu-api novu-worker novu-ws novu-dashboard

novu-down:
	docker compose -f compose.yaml stop mongodb redis novu-api novu-worker novu-ws novu-dashboard

novu-logs:
	docker compose -f compose.yaml logs -f novu-api novu-worker

novu-bootstrap:
	# Creates a Novu organization + project + initial API key. Idempotent.
	./scripts/novu-bootstrap.sh
```

`scripts/novu-bootstrap.sh` calls the Novu HTTP API to create a dev organization + environment + grab the API key, writes it to OpenBao KV at `secret/data/dep_local/notifications/novu_api_key`. Idempotent on re-run.

### 6.3 OpenAPI spec — Notifications endpoints

`openapi/data-plane.yaml` (additions):

```yaml
tags:
  - name: notification-channels
    description: BYOK vendor channel configurations (SMTP, SendGrid, SES, in-app).
  - name: notifications
    description: Send and inspect transactional notifications.
  - name: notification-workflows
    description: Mapping from platform workflow names to Novu workflow IDs.

paths:
  /v1/notification-channels:
    get:
      operationId: listNotificationChannels
      tags: [notification-channels]
      responses:
        "200": { content: { application/json: { schema: { $ref: "#/components/schemas/NotificationChannelListResponse" } } } }
    post:
      operationId: createNotificationChannel
      tags: [notification-channels]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/CreateNotificationChannelRequest" } } } }
      responses:
        "201":
          headers: { ETag: { schema: { type: string } } }
          content: { application/json: { schema: { $ref: "#/components/schemas/NotificationChannelResponse" } } }

  /v1/notification-channels/{channel_id}:
    parameters: [ { in: path, name: channel_id, required: true, schema: { type: string, pattern: "^chan_[0-9A-HJKMNP-TV-Z]{26}$" } } ]
    get:    { operationId: getNotificationChannel, tags: [notification-channels], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/NotificationChannelResponse" } } } } } }
    patch:  { operationId: updateNotificationChannel, tags: [notification-channels], parameters: [ { $ref: "#/components/parameters/IfMatch" }, { $ref: "#/components/parameters/IdempotencyKey" } ], requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/UpdateNotificationChannelRequest" } } } }, responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/NotificationChannelResponse" } } } } } }
    delete: { operationId: deleteNotificationChannel, tags: [notification-channels], parameters: [ { $ref: "#/components/parameters/IfMatch" } ], responses: { "204": { description: Deleted. } } }

  /v1/notification-channels/{channel_id}/rotate-credentials:
    post:
      operationId: rotateNotificationChannelCredentials
      tags: [notification-channels]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/RotateChannelCredentialsRequest" } } } }
      responses:
        "200": { content: { application/json: { schema: { $ref: "#/components/schemas/NotificationChannelResponse" } } } }

  /v1/notification-workflows:
    get:  { operationId: listNotificationWorkflows, tags: [notification-workflows], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/NotificationWorkflowListResponse" } } } } } }
    post: { operationId: registerNotificationWorkflow, tags: [notification-workflows], parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ], requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/RegisterNotificationWorkflowRequest" } } } }, responses: { "201": { content: { application/json: { schema: { $ref: "#/components/schemas/NotificationWorkflowResponse" } } } } } }

  /v1/notifications/send:
    post:
      operationId: sendNotification
      tags: [notifications]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/SendNotificationRequest" } } } }
      responses:
        "202":
          content: { application/json: { schema: { $ref: "#/components/schemas/SendNotificationResponse" } } }

  /v1/notifications/{notification_id}:
    parameters: [ { in: path, name: notification_id, required: true, schema: { type: string, pattern: "^notif_[0-9A-HJKMNP-TV-Z]{26}$" } } ]
    get:
      operationId: getNotification
      tags: [notifications]
      responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/NotificationResponse" } } } } }

components:
  schemas:
    NotificationChannel:
      type: object
      required: [id, object, provider, name, status, created_at, updated_at, etag]
      properties:
        id:        { type: string, pattern: "^chan_[0-9A-HJKMNP-TV-Z]{26}$" }
        object:    { type: string, enum: [notification_channel] }
        provider:  { type: string, enum: [smtp, sendgrid, ses, in_app] }
        name:      { type: string, minLength: 1, maxLength: 64 }
        status:    { type: string, enum: [active, disabled] }
        is_default_for:
          type: array
          items: { type: string, enum: [email, in_app] }
        # Credential fields are NEVER returned. The response shows only the
        # last-rotated date and a "credentials_present: true|false" flag.
        credentials_present: { type: boolean }
        last_rotated_at: { type: [string, "null"], format: date-time }
        created_at: { type: string, format: date-time }
        updated_at: { type: string, format: date-time }
        etag:       { type: string }

    CreateNotificationChannelRequest:
      type: object
      required: [provider, name, credentials]
      properties:
        provider: { type: string, enum: [smtp, sendgrid, ses, in_app] }
        name:     { type: string }
        is_default_for: { type: array, items: { type: string, enum: [email, in_app] } }
        credentials:
          # Shape varies by provider. Validated server-side after the persist
          # walker has envelope-encrypted the fields.
          oneOf:
            - $ref: "#/components/schemas/SMTPCredentials"
            - $ref: "#/components/schemas/SendGridCredentials"
            - $ref: "#/components/schemas/SESCredentials"
            - $ref: "#/components/schemas/InAppCredentials"

    SMTPCredentials:
      type: object
      required: [host, port, username, password]
      properties:
        host:     { type: string }
        port:     { type: integer, minimum: 1, maximum: 65535 }
        username: { type: string, x-oapi-codegen-extra-tags: { sensitive: "true" } }
        password: { type: string, x-oapi-codegen-extra-tags: { sensitive: "true", pii: "true" } }
        from:     { type: string, format: email }
        starttls: { type: boolean, default: true }

    SendGridCredentials:
      type: object
      required: [api_key, from]
      properties:
        api_key:  { type: string, x-oapi-codegen-extra-tags: { sensitive: "true", pii: "true" } }
        from:     { type: string, format: email }

    SESCredentials:
      type: object
      required: [access_key_id, secret_access_key, region, from]
      properties:
        access_key_id:     { type: string, x-oapi-codegen-extra-tags: { sensitive: "true" } }
        secret_access_key: { type: string, x-oapi-codegen-extra-tags: { sensitive: "true", pii: "true" } }
        region:            { type: string }
        from:              { type: string, format: email }

    InAppCredentials:
      type: object
      # No external creds — uses Novu's internal in-app channel.
      properties: {}

    UpdateNotificationChannelRequest:
      type: object
      properties:
        name:    { type: string }
        status:  { type: string, enum: [active, disabled] }
        is_default_for: { type: array, items: { type: string } }

    RotateChannelCredentialsRequest:
      type: object
      required: [credentials]
      properties:
        credentials: { oneOf: [
          { $ref: "#/components/schemas/SMTPCredentials" },
          { $ref: "#/components/schemas/SendGridCredentials" },
          { $ref: "#/components/schemas/SESCredentials" },
          { $ref: "#/components/schemas/InAppCredentials" }
        ] }

    NotificationWorkflow:
      type: object
      required: [id, object, name, novu_workflow_id, created_at]
      properties:
        id:                { type: string, pattern: "^wf_[0-9A-HJKMNP-TV-Z]{26}$" }
        object:            { type: string, enum: [notification_workflow] }
        name:              { type: string, minLength: 1, maxLength: 64 }
        novu_workflow_id:  { type: string }
        description:       { type: string }
        created_at:        { type: string, format: date-time }

    RegisterNotificationWorkflowRequest:
      type: object
      required: [name, novu_workflow_id]
      properties:
        name:             { type: string }
        novu_workflow_id: { type: string }
        description:      { type: string }

    SendNotificationRequest:
      type: object
      required: [workflow_name, to]
      properties:
        workflow_name: { type: string }
        to: { type: object, required: [user_id], properties: { user_id: { type: string } } }
        payload: { type: object, additionalProperties: true, x-oapi-codegen-extra-tags: { sensitive: "true" } }
        channel_overrides: { type: array, items: { type: string } }
        idempotency_marker: { type: string }

    SendNotificationResponse:
      type: object
      required: [data]
      properties:
        data:
          type: object
          required: [id, status, queued_at]
          properties:
            id:        { type: string, pattern: "^notif_[0-9A-HJKMNP-TV-Z]{26}$" }
            status:    { type: string, enum: [queued, sent, delivered, failed] }
            queued_at: { type: string, format: date-time }

    Notification:
      type: object
      required: [id, status, queued_at, workflow_name, to_user_id]
      properties:
        id:            { type: string }
        status:        { type: string, enum: [queued, sent, delivered, failed] }
        queued_at:     { type: string, format: date-time }
        sent_at:       { type: [string, "null"], format: date-time }
        delivered_at:  { type: [string, "null"], format: date-time }
        failed_at:     { type: [string, "null"], format: date-time }
        failure_reason: { type: [string, "null"] }
        workflow_name: { type: string }
        to_user_id:    { type: string }

    NotificationChannelListResponse: { type: object, required: [data], properties: { data: { type: array, items: { $ref: "#/components/schemas/NotificationChannel" } } } }
    NotificationChannelResponse:     { type: object, required: [data], properties: { data: { $ref: "#/components/schemas/NotificationChannel" } } }
    NotificationWorkflowListResponse:{ type: object, required: [data], properties: { data: { type: array, items: { $ref: "#/components/schemas/NotificationWorkflow" } } } }
    NotificationWorkflowResponse:    { type: object, required: [data], properties: { data: { $ref: "#/components/schemas/NotificationWorkflow" } } }
    NotificationResponse:            { type: object, required: [data], properties: { data: { $ref: "#/components/schemas/Notification" } } }
```

### 6.4 Migration — `migrations/dataplane/000004_notifications.up.sql`

```sql
CREATE TABLE notification_channel (
    id                text PRIMARY KEY CHECK (id LIKE 'chan_%'),
    tenant_id         text NOT NULL REFERENCES tenant (id),
    provider          text NOT NULL CHECK (provider IN ('smtp','sendgrid','ses','in_app')),
    name              text NOT NULL,
    is_default_for    text[] NOT NULL DEFAULT '{}',
    status            text NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active','disabled')),
    -- BYOK envelope-encrypted creds. Schema per provider; the application
    -- enforces shape via go-playground/validator at the handler boundary.
    -- One blob field per provider type avoids a sparse N-column matrix.
    creds_ciphertext  bytea,
    creds_wrapped_dek text,
    creds_nonce       bytea,
    creds_kid         text,
    creds_key_version integer,
    last_rotated_at   timestamptz,
    row_seq           bigint NOT NULL DEFAULT 1,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    deleted_at        timestamptz,
    UNIQUE (tenant_id, name) WHERE deleted_at IS NULL
);
CREATE TRIGGER notification_channel_bump_row_seq BEFORE UPDATE ON notification_channel FOR EACH ROW EXECUTE FUNCTION bump_row_seq();
ALTER TABLE notification_channel ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_channel FORCE  ROW LEVEL SECURITY;
CREATE POLICY notification_channel_tenant_only ON notification_channel USING (tenant_id = current_setting('app.current_tenant_id', true));

CREATE TABLE notification_workflow (
    id                text PRIMARY KEY CHECK (id LIKE 'wf_%'),
    tenant_id         text NOT NULL REFERENCES tenant (id),
    name              text NOT NULL,
    novu_workflow_id  text NOT NULL,
    description       text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
ALTER TABLE notification_workflow ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_workflow FORCE  ROW LEVEL SECURITY;
CREATE POLICY notification_workflow_tenant_only ON notification_workflow USING (tenant_id = current_setting('app.current_tenant_id', true));

CREATE TABLE notification (
    id              text PRIMARY KEY CHECK (id LIKE 'notif_%'),
    tenant_id       text NOT NULL REFERENCES tenant (id),
    workflow_name   text NOT NULL,
    to_user_id      text NOT NULL REFERENCES platform_user (id),
    payload_ciphertext bytea NOT NULL,
    payload_wrapped_dek text NOT NULL,
    payload_nonce      bytea NOT NULL,
    payload_kid        text NOT NULL,
    payload_key_version integer NOT NULL,
    novu_transaction_id text,
    status          text NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','sent','delivered','failed')),
    queued_at       timestamptz NOT NULL DEFAULT now(),
    sent_at         timestamptz,
    delivered_at    timestamptz,
    failed_at       timestamptz,
    failure_reason  text
);
CREATE INDEX notification_status_idx ON notification (tenant_id, status, queued_at DESC);
CREATE INDEX notification_user_idx   ON notification (tenant_id, to_user_id, queued_at DESC);
ALTER TABLE notification ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification FORCE  ROW LEVEL SECURITY;
CREATE POLICY notification_tenant_only ON notification USING (tenant_id = current_setting('app.current_tenant_id', true));
```

### 6.5 Module layout — `internal/dataplane/notifications/`

```text
internal/dataplane/notifications/
  domain.go
  ports.go        # Repository, NovuClient, EventPublisher, ChannelCredsCodec
  service.go
  repo_pgx.go
  novu_adapter.go # Novu REST client (handwritten; no SDK in MVP — see notes below)
  creds.go        # JSON encode/decode of per-provider credentials structs
  invitation.go   # Helper used by Phase 7 to send invite emails (lives here so Phase 7 just calls it)
  password_reset.go # Replaces Keycloak built-in SMTP for the user.password_reset_requested event
  handler.go
  errors.go
  service_test.go
  novu_adapter_test.go
  security_test.go
```

`ports.go`:

```go
package notifications

import "context"

type Repository interface {
    CreateChannel(ctx context.Context, c Channel) (Channel, error)
    GetChannel(ctx context.Context, tenantID, channelID string) (Channel, error)
    ListChannels(ctx context.Context, tenantID string) ([]Channel, error)
    UpdateChannel(ctx context.Context, tenantID, channelID string, seq int64, patch ChannelPatch) (Channel, error)
    DeleteChannel(ctx context.Context, tenantID, channelID string, seq int64) error
    RotateChannelCreds(ctx context.Context, tenantID, channelID string, newCreds Envelope) (Channel, error)

    RegisterWorkflow(ctx context.Context, tenantID, name, novuID, description string) (Workflow, error)
    ListWorkflows(ctx context.Context, tenantID string) ([]Workflow, error)
    GetWorkflowByName(ctx context.Context, tenantID, name string) (Workflow, error)

    CreateNotification(ctx context.Context, n Notification) (Notification, error)
    GetNotification(ctx context.Context, tenantID, id string) (Notification, error)
    UpdateNotificationStatus(ctx context.Context, id, status string, reason *string) error
}

type NovuClient interface {
    SetChannelCredentials(ctx context.Context, novuEnvID, provider, creds string) error
    TriggerWorkflow(ctx context.Context, novuEnvID, workflowID string, to string, payload map[string]any) (transactionID string, err error)
    GetWorkflowExecutionStatus(ctx context.Context, novuEnvID, transactionID string) (status string, err error)
}
```

`novu_adapter.go` is a handwritten REST client. **Note**: Novu publishes a TypeScript SDK only; for Go we hand-roll the REST client. The surface is small: `POST /v1/events/trigger`, `GET /v1/notifications/{id}`, `PUT /v1/integrations/{id}`. Verify URL shapes against Novu v3.15 docs at `https://docs.novu.co/api-reference` before implementation. v3 added the v2 management surface guarded by `IS_V2_ENABLED=true` (the v1 endpoints continue to work alongside).

### 6.6 Service flow — send notification

```go
func (s *Service) Send(ctx context.Context, tenantID string, req SendRequest) (Notification, error) {
    if err := auth.AssertTenant(ctx, tenantID); err != nil { return Notification{}, err }
    wf, err := s.repo.GetWorkflowByName(ctx, tenantID, req.WorkflowName)
    if err != nil { return Notification{}, err }

    // Persist the notification row first (transactional outbox).
    n := Notification{
        ID: id.New(id.PrefixNotification),
        TenantID: tenantID,
        WorkflowName: req.WorkflowName,
        ToUserID: req.ToUserID,
        PayloadPlaintext: marshalJSON(req.Payload),    // envelope-walker encrypts
        Status: "queued",
        QueuedAt: time.Now(),
    }
    n, err = s.repo.CreateNotification(ctx, n)
    if err != nil { return Notification{}, err }

    // Emit outbox event so Phase 10 audit catches it.
    _ = s.events.Publish(ctx, "notification.queued", tenantID, map[string]any{
        "notification_id": n.ID, "workflow_name": req.WorkflowName, "to_user_id": req.ToUserID,
    })

    // Trigger Novu out-of-band; the worker subscribes to outbox.
    return n, nil
}

// triggerSubscriber consumes `notification.queued` outbox events and calls Novu.
// Lives in cmd/dataplane/main.go wired as part of the outbox dispatcher.
```

The Novu trigger happens via outbox consumption so Novu failures don't block the request response (202 Accepted). The outbox subscriber:

1. Decrypts the payload (envelope.Decrypt with the deployment kid).
2. Looks up the user's email via Identity (`GetByID`).
3. Calls `NovuClient.TriggerWorkflow(novuEnvID, wf.NovuWorkflowID, user.Email, payload)`.
4. On success: `UpdateNotificationStatus(id, "sent", nil)` + emit `notification.sent`.
5. On failure: `UpdateNotificationStatus(id, "failed", err.Error())` + emit `notification.delivery_failed`.

### 6.7 BYOK channel credentials — the persist walker

The `Channel.Creds` field is an opaque JSON blob that varies by provider. Sketch:

```go
type Channel struct {
    ID, TenantID, Provider, Name string
    Status string
    IsDefaultFor []string

    // Decrypted in-memory only; cleared after use.
    CredsPlaintext []byte `pii:"true" sensitive:"true"`
    CredsEnvelope  envelope.Envelope

    LastRotatedAt *time.Time
    RowSeq        int64
    CreatedAt, UpdatedAt time.Time
}
```

The persist walker (Phase 4) encrypts `CredsPlaintext` into `CredsEnvelope` on insert/update; the response handler zeroes `CredsPlaintext` and emits the channel WITHOUT the creds field. The §17.3 matrix includes "GET channel does not leak any credential bytes" as a test.

When Novu needs the channel creds (the outbox subscriber configuring an integration), the service:

1. Reads the channel row.
2. Calls `envelope.Decrypt(ctx, channel.CredsEnvelope, deploymentID, aad)`.
3. Unmarshals JSON into the provider-specific struct (`SMTPCreds`, `SendGridCreds`, ...).
4. Calls `NovuClient.SetChannelCredentials(novuEnvID, "smtp", smtpJSON)`.
5. Zeros the plaintext slice.
6. Emits an audit event `notification_channel.credentials_read` per §18.7.

### 6.8 Rotation

`POST /v1/notification-channels/{id}/rotate-credentials`:

1. AssertTenant.
2. Validate the new credentials struct shape via go-playground.
3. Encrypt and persist; bump `row_seq`; set `last_rotated_at = now()`.
4. Update the Novu integration with the new creds.
5. Emit `notification_channel.credentials_rotated` audit event.
6. Return the channel (NO creds in body; the rotation request body is the only place the new creds are seen — Stripe pattern).

Per ADR 017, rotation is a distinct verb; PATCH never accepts credentials.

### 6.9 Identity rewire — password reset via Notifications

Update Phase 5's `triggerPasswordReset` flow:

```go
func (s *Service) TriggerPasswordReset(ctx context.Context, tenantID, userID string) error {
    if err := auth.AssertTenant(ctx, tenantID); err != nil { return err }
    u, err := s.repo.Get(ctx, tenantID, userID)
    if err != nil { return err }
    // Keycloak still generates the reset token, but we send the email via Notifications.
    resetURL, err := s.kc.GeneratePasswordResetToken(ctx, s.realmFor(tenantID), u.KeycloakUserID)
    if err != nil { return err }
    return s.notifications.Send(ctx, tenantID, notifications.SendRequest{
        WorkflowName: "user.password_reset",
        ToUserID:     u.ID,
        Payload:      map[string]any{"reset_url": resetURL, "expires_in_minutes": 60},
    })
}
```

The realm template authored in Phase 5 keeps a `password-reset` workflow registered by default in Novu so this works out of the box. Phase 6 adds a `make notifications-seed-default-workflows` target that creates the default workflows (password_reset, email_verify, invitation) at bootstrap.

### 6.10 ADRs

`docs/adr/013-notifications-novu-mvp.md`:

```markdown
# ADR 013 — Promote Notifications module (Novu wrapper) to MVP

## Status
Accepted (2026-05-24).

## Context
Original AGENTS.md §15 listed Notifications in v1 roadmap. User feedback
(2026-05-24): every other MVP module needs to send transactional email
(invitations, password reset, email verify). Building a stub mailer and
swapping later is more work than wrapping Novu from day one.

## Decision
Promote Notifications to MVP. MVP channels: email (via SMTP / SendGrid / SES
BYOK) and in-app (via Novu's built-in channel). SMS / WhatsApp / push remain
v1 roadmap.

Module wraps Novu via REST. Novu runs in compose (6 containers:
mongodb, redis, novu-api, novu-worker, novu-web, novu-ws).

Channel credentials are BYOK — per-Deployment, envelope-encrypted via
OpenBao Transit. See ADR 017 for details.

## Consequences
+ All transactional email flows have a single source of truth.
+ Operators can author templates in Novu's web UI (Phase 6 wires novu-web).
+ No need to build a template engine or per-provider SDK adapters.
- Six new containers in compose; documented + pinned.
- Novu has its own MongoDB; one more storage backend to back up.
- Novu version pin is on v3.15.0 (no separate LTS branch; v3.x rolls forward on minors with low self-hoster breakage). Bump to v3.16.x is a single-line Makefile change; verify the compose env-var set hasn't grown.
```

`docs/adr/017-byok-vendor-credentials.md`:

```markdown
# ADR 017 — BYOK vendor credentials: envelope encryption + rotation API + audit

## Status
Accepted (2026-05-24).

## Context
Per §18.7, vendor credentials (SMTP, SendGrid, SES) are sensitive at rest.
Storing them in OpenBao KV every read adds round-trip latency on the send hot
path. We need a scheme that:
- Encrypts creds at rest with per-Deployment key binding.
- Allows constant-time lookup at send time.
- Audits every credential read.
- Supports explicit rotation (Stripe-style: distinct verb).

## Decision
Store creds as envelope-encrypted columns on the channel row (Phase 4 walker).
AAD = `deployment_id || "notification_channel" || channel_id`. kid =
deployment_id. The persist walker encrypts on insert/update; the service
decrypts on send and zeros the plaintext immediately.

Rotation endpoint: `POST /v1/notification-channels/{id}/rotate-credentials`
with a request body containing the new creds shape. PATCH does NOT accept
credentials — separation prevents accidental rotation via metadata edits.

Audit: every decrypt emits `notification_channel.credentials_read` with the
actor + channel_id + provider (NOT the creds themselves).

## Consequences
+ Per-channel rotation without re-encrypting other rows.
+ Audit trail per credential access (compliance).
- Decrypt latency on every send (one OpenBao round-trip per channel). For
  high-volume tenants, plan a per-channel decrypt cache with short TTL — out
  of MVP.
- Schema is provider-shape-validated at the handler; codegen does NOT
  enforce. Validator + test cover the matrix.
```

### 6.11 Tests

`security_test.go` — the §17.3 matrix:

| Test | Assert |
|---|---|
| GET channel as wrong tenant | 404 (no existence leak) |
| GET channel returns no credential bytes | response body has `credentials_present: true`, no creds field |
| Create channel with malformed SMTP creds | 422 problem with field errors |
| Rotate credentials with empty body | 422 |
| Rotate credentials cross-tenant | 404 |
| Send with workflow_name belonging to other tenant | 404 |
| Send replays Idempotency-Key | 202 with same notification_id |
| Send to non-existent user_id | 404 |
| Send when no default channel | 422 `no-default-channel-configured` |

`novu_adapter_test.go` (testcontainers Novu):

- Set integration creds → Novu API responds 200
- Trigger workflow → transaction_id returned
- Get transaction status → "queued" → "sent"

`service_test.go` (mocks):

- Decrypt fails → status="failed", failure_reason set, audit event emitted
- Cred read emits audit event

### 6.12 TS SDK + workflow wrapper

```bash
make sdk-ts
```

`sdk/ts/data-plane/workflows/notifications.ts` exposes `send`, `listChannels`, `createChannel`, `rotateCredentials`, `getNotification`.

### 6.13 saasctl

```text
saasctl notification-channel create --provider sendgrid --name primary --api-key XXX --from foo@bar
saasctl notification send --workflow user.password_reset --to user_XYZ --payload-file payload.json
saasctl notification-channel rotate <chan_id> --provider sendgrid --api-key NEW
```

### 6.14 Commits

```bash
git add compose.yaml Makefile scripts/novu-bootstrap.sh
git commit -m "add novu stack to compose"

git add openapi/data-plane.yaml openapi/problems/
git commit -m "add notifications and channel endpoints"

git add migrations/dataplane/000004_notifications.up.sql internal/dataplane/db/queries/notifications.sql
git commit -m "add notification tables with byok creds"

git add internal/dataplane/notifications/
git commit -m "implement notifications module wrapping novu"

git add internal/dataplane/identity/  # password_reset rewire
git commit -m "rewire user password reset through notifications"

git add sdk/ts/data-plane/workflows/notifications.ts cmd/saasctl/
git commit -m "ts sdk and saasctl notifications coverage"

git add docs/adr/013-notifications-novu-mvp.md docs/adr/017-byok-vendor-credentials.md
git commit -m "add notifications and byok adrs"
```

---

## Verification checklist

```bash
# 1. Novu stack boots.
$ make compose-down && make compose-up && make novu-bootstrap
$ curl -sf http://localhost:3000/v1/health-check && echo ok

# 2. Migrations apply.
$ make migrate
$ psql -c "\d notification_channel" -c "\d notification" -c "\d notification_workflow"

# 3. OpenAPI + lint clean.
$ make openapi-check && make lint

# 4. Tests pass.
$ make test && make test-int

# 5. §17.3 matrix.
$ go test -run TestNotifications_AuthZ -v ./internal/dataplane/notifications/...

# 6. Create a channel, rotate, never see creds in any GET.
$ JSON='{"provider":"smtp","name":"primary","credentials":{"host":"mailhog","port":1025,"username":"x","password":"y","from":"noreply@example.test","starttls":false}}'
$ curl -s -X POST http://localhost:9090/v1/notification-channels \
    -H "Authorization: Bearer $TOK" -H "Idempotency-Key: idem_..." -H "Content-Type: application/json" \
    -d "$JSON" | jq .
# Expected: 201; credentials_present: true; no creds bytes in response
$ curl -s http://localhost:9090/v1/notification-channels/<id> -H "Authorization: Bearer $TOK" | jq '. | keys'
# Expected: id, provider, name, status, is_default_for, credentials_present, last_rotated_at, ... — no creds

# 7. Register a workflow and send.
$ curl -s -X POST http://localhost:9090/v1/notification-workflows ... -d '{"name":"user.password_reset","novu_workflow_id":"<from novu>","description":"..."}'
$ curl -s -X POST http://localhost:9090/v1/notifications/send ... -d '{"workflow_name":"user.password_reset","to":{"user_id":"user_..."},"payload":{"reset_url":"https://..."}}'
# Expected: 202 with notif_<ulid>, status=queued

# 8. Email arrives in mailhog.
$ curl -s http://localhost:8025/api/v2/messages | jq '.items | length'
# Expected: >= 1

# 9. Identity password reset uses Notifications.
$ curl -s -X POST http://localhost:9090/v1/users/<id>/reset-password ...
# Expected: 202; email in mailhog with the password reset link

# 10. Audit row emitted on creds read.
$ docker compose exec openbao bao read sys/audit
$ docker compose logs openbao | tail -20  # OpenBao audit log
# Expected: an entry for transit/decrypt/<dep_id> with notification_channel context
```

---

## Anti-pattern guards

- **NEVER** return channel credentials in any GET / LIST response. The OpenAPI schema does not declare a `credentials` field on the response — codegen enforces.
- **NEVER** store SendGrid/SES API keys via PATCH. Rotation is the only endpoint that accepts new creds.
- **NEVER** trigger Novu synchronously from the request handler. The outbox subscriber consumes `notification.queued`. Failure does NOT bubble to the client; it surfaces in the notification's status field.
- **NEVER** call `NovuClient.TriggerWorkflow` without `to.user_id`. The Novu subscriberId is the platform user_id — never the email — so PII never leaves the platform DB unless explicitly chosen.
- **NEVER** skip the audit emit on `credentials_read`. §18.7 makes it mandatory.
- **NEVER** widen the workflow shape to accept inline templates from API callers. Templates live in Novu; the API stores only the name→id mapping.
- **NEVER** hard-code the Novu `JWT_SECRET` / `STORE_ENCRYPTION_KEY` in production compose overlays. Phase 12e wires per-Deployment values from OpenBao KV.
- **NEVER** mutate the existing notification's status field directly from a handler. Status transitions belong to the outbox subscriber.

---

## Open questions

1. **Novu image tag** — resolved pre-execution: `ghcr.io/novuhq/novu/<service>:3.15.0`. Five services: `api`, `worker`, `ws`, `dashboard` (replaces legacy `web`), plus `mongo` and `redis`. New required env `NOVU_SECRET_KEY`; `STORE_ENCRYPTION_KEY` must be EXACTLY 32 characters or boot fails silently. Verify `https://github.com/novuhq/novu/pkgs/container/novu%2Fapi` at execution for any `3.16.x` bump.
2. **Default workflows seeded at bootstrap.** Default: `user.password_reset`, `user.email_verify`, `member.invited`. Confirm naming.
3. **In-app delivery surface.** Novu's `novu-ws` container provides WebSocket-based in-app notifications. Platform exposes a `/v1/me/notifications` endpoint for in-app stream? Default: yes, but **defer to Phase 7 or Phase 15** — Phase 6 only ships email + the in-app channel config (no API for end-users yet).
4. **Per-tenant Novu environment vs per-Deployment.** Default: per-Deployment (one Novu org per Deployment). Per-tenant would be cleaner but Novu's hierarchy is org→environment→workflow; mapping tenant→environment costs an extra hop. Confirm per-Deployment.

---

## Phase 6 — Definition of done

- [ ] Novu stack added to compose; `make novu-bootstrap` idempotent
- [ ] Migrations 000004 applied; `notification_channel`, `notification_workflow`, `notification` exist with RLS
- [ ] `internal/dataplane/notifications/` complete with handler + service + repo + Novu adapter + tests
- [ ] BYOK credentials envelope-encrypted via Phase 4 walker; rotation endpoint distinct
- [ ] `notification.queued` outbox event → Novu trigger flow E2E
- [ ] Identity password reset rewired through Notifications; mailhog receives
- [ ] §17.3 matrix tests pass for every Notifications endpoint
- [ ] Audit event emitted on every credential read (Phase 10 will consume)
- [ ] TS SDK regenerated + workflow wrapper added
- [ ] saasctl `notification-channel`, `notification` subtrees
- [ ] ADRs 013 + 017 committed
- [ ] All Phase 2-5 tests still green
- [ ] PR template, `ready` label, CI green

---

## CHECKPOINT 2 — Crypto and Notifications ready (continued from Phase 4)

> Note: 00-master.md gates CHECKPOINT 2 after Phase 6. Phase 4 produced the
> envelope library; Phase 6 produced the first production consumer (BYOK
> channel creds). The combined checkpoint is here.

### What was done (Phase 6 portion)
- compose.yaml: mongodb, redis, novu-api, novu-worker, novu-web, novu-ws containers added; healthchecks wired
- Makefile: novu-up, novu-down, novu-bootstrap, notifications-seed-default-workflows
- migrations/dataplane/000004_notifications.up.sql
- internal/dataplane/notifications/{domain,ports,service,repo_pgx,novu_adapter,creds,invitation,password_reset,handler,errors}.go
- internal/dataplane/identity/service.go (TriggerPasswordReset rewired)
- openapi/data-plane.yaml: /v1/notification-channels, /v1/notification-workflows, /v1/notifications endpoints
- sdk/ts/data-plane/workflows/notifications.ts
- docs/adr/013-notifications-novu-mvp.md, docs/adr/017-byok-vendor-credentials.md

### What to verify (user runs these)
```bash
$ make compose-up && make novu-bootstrap && make migrate
$ curl -sf http://localhost:3000/v1/health-check && echo ok
$ make test && make test-int
$ go test -v -run TestNotifications_AuthZ ./internal/dataplane/notifications/...

# Create channel; confirm no creds leak on any read.
$ curl -X POST http://localhost:9090/v1/notification-channels -H "Authorization: Bearer $TOK" -H "Idempotency-Key: idem_..." -d '{"provider":"smtp","name":"primary","credentials":{"host":"mailhog","port":1025,"username":"u","password":"p","from":"x@y","starttls":false}}'
$ curl http://localhost:9090/v1/notification-channels/<id> -H "Authorization: Bearer $TOK" | jq
# Expected: no "credentials" field; "credentials_present":true; "last_rotated_at" populated after rotation

# Trigger password reset via Identity → email lands in mailhog.
$ curl -X POST http://localhost:9090/v1/users/<id>/reset-password -H "Authorization: Bearer $TOK" -H "Idempotency-Key: idem_..."
$ curl http://localhost:8025/api/v2/messages | jq '.items[0].Content.Headers.Subject'
# Expected: "Update your password"

# Rotate creds; observe audit row.
$ curl -X POST http://localhost:9090/v1/notification-channels/<id>/rotate-credentials -H "Authorization: Bearer $TOK" -H "Idempotency-Key: idem_..." -d '{"credentials":{"host":"mailhog","port":1025,"username":"u","password":"NEW","from":"x@y","starttls":false}}'
# After Phase 10 audit ships, this row exists in audit_event with action=notification_channel.credentials_rotated
```

### What approval means
By proceeding past CHECKPOINT 2, you accept:
- Notifications module shape (channels + workflows + send) is frozen as the public API; breaking it requires /v2 + 6-month overlap per §27.
- BYOK rotation API is a distinct verb; PATCH never accepts creds.
- The Novu stack adds ~6 containers + 2 storage backends (MongoDB, Redis) to every Deployment. Phase 12e will replicate this per Deployment.
- Identity password-reset is now coupled to Notifications; an outage in Novu breaks password recovery (the Keycloak fallback is documented in the runbook).

### Rollback if rejected
```bash
git revert <hashes for the 7 phase-6 commits>
docker compose stop mongodb redis novu-api novu-worker novu-web novu-ws
# Identity falls back to its Phase-5 Keycloak SMTP path automatically.
```

---

End of Phase 6. Next: `08-organizations.md`.
