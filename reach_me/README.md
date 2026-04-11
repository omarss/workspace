# reach_me

Minimal NestJS service skeleton for a self-hosted POC that accepts a request:

- Mobile number (E.164 format, includes country code)
- Message (free text)
- Language (en or ar)
- Channel (whatsapp_text, whatsapp_voice, call)
- Returns a confirmation state (confirmed, rejected, not_confirmed)

This repository is intentionally minimal. It stores requests in memory by default so you can validate
flow before integrating real channel providers, and can be configured to persist to Cassandra.

## Local development

Requirements:
- Bun 1.3.5+

Install:
- bun install

Run:
- cp .env.example .env
- bun run start:dev

Health:
- GET http://localhost:3000/health

Create request:
- POST http://localhost:3000/v1/engage

Example body:
```json
{
  "mobileNumber": "+201234567890",
  "message": "some free text message",
  "language": "en",
  "channel": "whatsapp_text"
}
```

Get request status:
- GET http://localhost:3000/v1/engage/{requestId}

Manually set result (simulates callback/webhook):
- POST http://localhost:3000/v1/engage/{requestId}/result
```json
{ "result": "confirmed" }
```

## Auth and rate limiting

If `API_KEY` is set, requests must include it via `x-api-key` or
`Authorization: Bearer <token>`.

Rate limits are configured with:
- `RATE_LIMIT_TTL_SECONDS` (default 60)
- `RATE_LIMIT_MAX` (default 60)

## Provider integrations

Create requests trigger a dispatch to the configured provider. Webhook endpoints
are public but can be verified with provider-specific secrets.

### WhatsApp (Meta Cloud API)

Outbound config:
- `WHATSAPP_PROVIDER=meta`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_API_VERSION` (default `v20.0`)

Webhook verification:
- `WHATSAPP_VERIFY_TOKEN` (for GET verification)
- `WHATSAPP_APP_SECRET` (optional signature verification)

Webhook endpoints:
- `GET /webhooks/whatsapp`
- `POST /webhooks/whatsapp`

Message modes:
- `WHATSAPP_MESSAGE_MODE=text|interactive|template` (default `text`)
- Interactive buttons: `WHATSAPP_CONFIRM_LABEL_EN`, `WHATSAPP_REJECT_LABEL_EN`,
  `WHATSAPP_CONFIRM_LABEL_AR`, `WHATSAPP_REJECT_LABEL_AR`,
  `WHATSAPP_CONFIRM_PAYLOAD`, `WHATSAPP_REJECT_PAYLOAD`
- Templates: `WHATSAPP_TEMPLATE_NAME`, `WHATSAPP_TEMPLATE_LANGUAGE`,
  `WHATSAPP_TEMPLATE_LANGUAGE_EN`, `WHATSAPP_TEMPLATE_LANGUAGE_AR`,
  `WHATSAPP_TEMPLATE_BODY_PARAM=message|none`,
  `WHATSAPP_TEMPLATE_BUTTONS=confirm_reject|none`

Voice notes:
- `WHATSAPP_VOICE_MODE=text|audio_link|audio_id`
- `WHATSAPP_VOICE_MEDIA_URL` or `WHATSAPP_VOICE_MEDIA_ID`

### Twilio (optional)

Shared config:
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `PUBLIC_BASE_URL` (required for callbacks)
- `TWILIO_VALIDATE_SIGNATURE=true` (optional)

WhatsApp via Twilio:
- `WHATSAPP_PROVIDER=twilio`
- `TWILIO_WHATSAPP_FROM=whatsapp:+15551234567`
- Optional override: `TWILIO_STATUS_CALLBACK_URL`

Call via Twilio:
- `CALL_PROVIDER=twilio`
- `TWILIO_CALL_FROM=+15551234567`

Webhook endpoints:
- `POST /webhooks/twilio/whatsapp/status`
- `POST /webhooks/twilio/whatsapp/inbound`
- `POST /webhooks/twilio/voice`
- `POST /webhooks/twilio/voice/confirm`

### Slack fallback

If a provider send fails, a Slack notification is sent when configured:
- `SLACK_WEBHOOK_URL`
- `SLACK_FALLBACK_INCLUDE_MESSAGE=false`

### AI message composer (Gemini)

Optional rewrite before sending:
- `AI_MESSAGE_PROVIDER=gemini`
- `AI_MESSAGE_CHANNELS=all`
- `GEMINI_API_KEY`
- `GEMINI_MODEL` (default `gemini-1.5-flash`)
- `GEMINI_API_BASE` (default `https://generativelanguage.googleapis.com`)

## Queue worker (pg-boss)

Dispatches can be queued and retried via Postgres using pg-boss.
If no connection string is set, dispatch happens inline.
pg-boss requires a Postgres instance and a Node 22+ compatible runtime.

Config:
- `PG_BOSS_CONNECTION_STRING` (or `DATABASE_URL`)
- `PG_BOSS_QUEUE_NAME` (default `engage-dispatch`)
- `PG_BOSS_RETRY_LIMIT` (default 3)
- `PG_BOSS_RETRY_DELAY_SECONDS` (default 30)
- `PG_BOSS_RETRY_BACKOFF` (default false)
- `PG_BOSS_BATCH_SIZE` (default 5)
- `PG_BOSS_POLL_INTERVAL_SECONDS` (default 5)
- `PG_BOSS_WORKER_ENABLED` (default true)

## Persistence (Cassandra)

By default, requests are stored in memory. To enable Cassandra persistence:

- Set `ENGAGE_STORE=cassandra`
- Configure connection details in `.env`
- Ensure the keyspace exists before running the service:
```sql
CREATE KEYSPACE IF NOT EXISTS reach_me
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};
```

The service will create the `confirmation_requests` table if it does not exist.

## Docker

Build:
- docker build -t reach_me:local .

Run:
- docker run --rm -p 3000:3000 reach_me:local

## Docker Compose (app + Cassandra)

Start:
- docker compose up --build

Stop:
- docker compose down

## Notes for next steps

- Harden Cassandra persistence (migrations, TTL/retention, replication strategy).
- Improve observability (structured logs, metrics, tracing).
- Expand tests for validation errors, not-found paths, and Cassandra-backed flows.


## Deterministic installs

For repeatable builds, generate and commit a lockfile:
- bun install
- git add bun.lock

For CI or strict reproducibility:
- bun ci
