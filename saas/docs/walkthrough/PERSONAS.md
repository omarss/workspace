# Persona walkthrough placeholders

This file is the parking lot for the four persona pages that Phase 15's
scope cut deferred. The Phase 15 plan called for six HTML pages (one
per persona); we shipped only `operator.html` as the exemplar so the
markup pattern is established. The remaining four — listed below — get
expanded into full HTML pages in a follow-up DX pass.

Each page should follow the same structure as `operator.html`:

```text
<header>         "<Persona> Walkthrough" + one-line goal
<nav>            persona switcher (highlight the current one)
<main>
  Who you are
  Prerequisites
  5-7 steps, each with:
    - title (one verb)
    - one CLI snippet
    - one curl snippet (or one SDK snippet)
    - expected output
    - link to the underlying recipe in ../recipes/
  What to read next
<footer>
```

Use `styles.css` as-is — no new CSS rules; the existing palette has
been validated against ~3 KB.

---

## Product Builder

Goal: embed the data-plane SDK in a customer-facing app.

Tasks to cover:

1. Bootstrap a Tenant against a Deployment (`create-tenant` recipe).
2. Create an API key for the app's backend (`create-api-key` recipe).
3. Wire the TS SDK in a Next.js page (`/v1/tenants` list).
4. Call `/v1/authorization/check` from the frontend
   (`check-authorization` recipe).
5. Stream notifications to an in-app inbox (Novu websocket).
6. Rotate the API key when CI starts logging it
   (`rotate-api-key` workflow).
7. Verify the JCS-canonical audit hash from the backend
   (`view-audit-events` recipe).

Notes for the author: emphasise that the SDK
(`@omarss/saas-dataplane-sdk`) is generated from the OpenAPI; SDK
upgrades are mechanical, not manual.

---

## Tenant Admin

Goal: configure a tenant for its first users.

Tasks to cover:

1. Create the tenant + default Organization (`create-tenant`).
2. Invite the first members (`invite-member`).
3. Assign roles (`assign-role`).
4. Configure a notification channel (BYOK SMTP / SendGrid; ADR 017).
5. Verify a check (`check-authorization`).
6. View the tenant audit log (`view-audit-events`).

Notes: BYOK rotation is one screen; emphasise that the secret is
envelope-encrypted at rest (ADR 017).

---

## End User

Goal: sign up, log in, link a social provider, accept an invitation.

Tasks to cover:

1. Sign up via the OIDC PKCE flow (Keycloak data-realm).
2. Verify email (Mailhog dev flow; real SMTP in prod).
3. Accept an invitation (`invite-member` recipe, recipient view).
4. Link a Google account (`link-social-provider`).
5. Reset password (data-plane endpoint).
6. Disable / enable own account.

Notes: this is the only persona page where curl is secondary — most
users live in a browser. Lead with screenshots; defer the API to a
"Power user" subsection.

---

## Machine Client

Goal: integrate a CI / scheduler / backend service.

Tasks to cover:

1. Create a scoped API key (`create-api-key`).
2. Implement Idempotency-Key in the client library.
3. Handle 410 Gone on stale cursors (ADR 011).
4. Send a notification on a deploy event (`send-notification`).
5. Rotate when leaked (`rotate-api-key`).
6. Read the audit chain from another service
   (`view-audit-events`).
7. Mount the OpenBao AppRole if the integration runs in k3s.

Notes: this page should compile cleanly into a one-liner cheat sheet
for the most common pitfalls (Idempotency, cursor versioning, 422 on
body-hash mismatch).

---

## Screenshots

The `screenshots/` directory holds reference PNGs for these pages
(none committed by default). Add captures as needed; name them
`<persona>-<step>.png` (e.g. `operator-step-3.png`) and reference
inline with `<img>` tags constrained to `max-width: 100%`.

When generating screenshots for the eventual full set: use a browser
window pinned at 1280x800 and capture only the relevant pane to keep
the asset weight reasonable.
