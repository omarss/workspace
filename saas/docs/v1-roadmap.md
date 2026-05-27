# v1 Roadmap (post-MVP)

Authored at MVP-cut. Items are listed in user-priority order.
Source: AGENTS.md §15.1 + Phase 16 verification gaps.

1. **Newsletters** — broadcast via Novu; subscriber lists; opt-in;
   GDPR / PDPL unsubscribe. Reuses Phase 6 channel + workflow infra.
   (User-requested priority.)
2. **SMS / WhatsApp channels** — extends notifications with Twilio +
   WhatsApp Cloud API providers.
3. **Plans, Subscriptions, Billing** — Lago wrapper (AGENTS.md §8.7.1).
4. **Entitlements + Limits** — feature flagging on the entitlement axis
   (§8.7.2).
5. **Files** — MinIO / S3 wrapper; presign upload / download (§8.7.4).
6. **Webhooks** — own outbox + delivery worker; signature verification
   helpers in SDKs (§8.7.5).
7. **Feature Flags** — OpenFeature + a local provider (§8.7.6).
8. **Analytics** — PostHog integration (§8.7.7).
9. **Support (Chatwoot)** — §8.7.8.
10. **Multi-replica policy sync** — Redis watcher for Casbin (ADR 005).
11. **Multi-replica rate limiter** — Redis-backed; replaces Phase 9
    in-process bucket.
12. **OpenBao dynamic database secrets engine** — opt-in per Deployment.
13. **Cloud KMS auto-unseal** — ADR 006 production path.
14. **Per-Deployment Keycloak realms (real)** — Phase 5 used a single
    shared realm; v1 wires per-Deployment realms.
15. **Email change flow** — Phase 5 deferred this user-attribute change.
16. **Audit async export** — Phase 10 ships sync-only; ≥ 1 MB exports
    trigger async with polling.
17. **Audit external chain anchor** — weekly Sigsum-style transparency log
    push.
18. **v1 RBAC hardening** — promote the §17.3 cross-tenant / role / scope
    matrix to **all** mutating endpoints (Phase 8 partial-retrofit covers 6
    endpoints today; the rest gate on `auth.AssertTenant` only).
19. **Control-plane authz matrix** — adapt the §17.3 8-case shape to the
    operator surface (currently gated by `auth.RequireScope` +
    step-up MFA, no per-tenant matrix because the resource is a
    deployment, not a tenant).
