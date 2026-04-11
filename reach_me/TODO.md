# TODO

- [x] Add auth (API key or JWT) and rate limiting for public exposure.
- [x] Add provider integrations (WhatsApp text/voice, call) with webhook/callback handling.
- [x] Add WhatsApp interactive buttons/templates (Meta Cloud API).
- [x] Add a background worker/queue for send/retry flows.
- [x] Support configurable WhatsApp confirm/reject payloads and labels in webhook handling.
- [x] Prevent Twilio WhatsApp provider from handling voice requests.
- [x] Log when a configured provider does not support the requested channel.
- [x] Add tests for validation errors, not-found paths, and webhook mapping.
- [ ] Harden Cassandra persistence (migrations, TTL/retention, replication strategy).
- [ ] Improve observability (structured logs, metrics, tracing).
- [x] Expand tests for Cassandra-backed flows.
- [ ] Document deployment/runbook details and required environment variables.
