# ADR 014 — Promote social login (Keycloak IdP brokering) to MVP

## Status

Accepted (2026-05-24, Phase 5).

## Context

The original AGENTS.md §8.3 listed only password + email flows for MVP.
User feedback during Phase 5 planning called out that B2B SaaS without
Google / GitHub login fails first-impression sign-up rates. Apple is
required by App Store guidelines for any iOS app that also offers other
third-party social logins.

Keycloak ships full Identity Brokering support out of the box (OAuth 2.0 +
OpenID Connect to external IdPs). Wiring it requires:

- Realm-level IdP broker configs for each provider (client_id, client_secret,
  scopes, callback URL).
- A platform endpoint that initiates the link flow.
- Persistent storage of `(platform_user_id, provider, external_subject)`
  mappings — needed for unlink + audit.
- CSRF protection on the link initiation (5-minute opaque state token).

The most security-sensitive question is: **how does the platform endpoint
attach a verified external identity to a platform user?** gocloak v14
exposes three typed methods on `*GoCloak`:

```go
GetUserFederatedIdentities(ctx, token, realm, userID string) ([]*FederatedIdentityRepresentation, error)
CreateUserFederatedIdentity(ctx, token, realm, userID, providerID string, rep FederatedIdentityRepresentation) error
DeleteUserFederatedIdentity(ctx, token, realm, userID, providerID string) error
```

The naïve approach — calling `CreateUserFederatedIdentity` directly — is
**a security hole**. The method requires a `userID` field on the
`FederatedIdentityRepresentation` (the external IdP's `sub` claim). The
platform endpoint cannot know that value without doing the OAuth dance
itself. Inserting any guessed / forged value enables account takeover:
anyone with the `manage-users` admin role could attach a victim's Google
identity to an attacker's platform user, after which the victim's next
Google login at Keycloak's broker endpoint logs them into the attacker's
account.

The correct primitive is Keycloak's **client-initiated account linking**
endpoint:

```
GET /realms/<realm>/broker/<provider>/link
    ?client_id=<client>
    &redirect_uri=<return_to>
    &nonce=<random>
    &hash=base64url(sha256(nonce + session_state + issued_for + provider))
```

The user's browser is redirected here. Keycloak runs the OAuth dance with
the external IdP using its own configured client credentials, gets back a
verified `sub`, and writes the `federated_identity` row itself. The user
must hold the `account.manage-account-links` role for Keycloak to accept
the request, which provides the proof-of-possession the direct-API method
lacks.

## Decision

**Promote social login to MVP. Providers: Google, GitHub, Apple.**

Implementation:

1. Platform endpoints:
   - `GET /v1/users/{id}/social-providers` → calls
     `GetUserFederatedIdentities` directly (read-only, safe).
   - `POST /v1/users/{id}/social-providers` → mints the hashed link URL
     described above and returns it. Caller redirects the browser; Keycloak
     completes the link. **Does NOT call CreateUserFederatedIdentity.**
   - `DELETE /v1/users/{id}/social-providers/{provider}` → calls
     `DeleteUserFederatedIdentity` directly (safe — no proof-of-possession
     needed to detach).

2. `identity_provider_mapping` table stores the
   `(platform_user_id, provider, external_subject)` triple — a local copy
   for audit queries that does not need a Keycloak round-trip.

3. `social_login_state` table stores opaque random tokens with 5-minute TTL,
   binding the user, provider, return_to URL, and the nonce that goes into
   the Keycloak hash. CSRF + replay protection.

4. `CreateUserFederatedIdentity` is reserved for operator / migration
   flows — the Control Plane's bulk-import API can use it when verified
   provider subjects are available. **Never expose on a user-facing endpoint.**

Phase 5 wires Google, GitHub, Apple as broker configs in the
`saas-data-local` realm template. Apple is disabled by default in dev (it
requires an Apple Developer Program enrolment); production turn-on requires
the operator to populate `apple.team_id`, `apple.client_id`,
`apple.private_key`, `apple.key_id` in OpenBao KV at
`secret/data/<deployment_id>/identity/providers/apple`.

## Consequences

### Positive

- Standard Keycloak feature; no custom OAuth code.
- Adding a provider later (Microsoft, Facebook, LinkedIn) is a realm-config
  change plus an enum extension + ADR — no new SDK methods.
- Security correctness flows from Keycloak running the OAuth dance with
  proof-of-possession at the realm boundary.

### Negative

- IdP credentials are per-Deployment; Phase 6 adds the OpenBao KV path for
  storing them, but until that lands the operator hand-edits the realm.
- gocloak v14 has no first-class "build hashed link URL" helper; we
  construct it manually in `provider_kc.go`. If the URL pattern changes in
  Keycloak 27, the adapter test (`TestStartSocialLogin_URLShape`) catches
  the regression before it reaches production.

### Phase 5 trade-offs

- The platform does NOT host the `/v1/social/callback` endpoint in Phase 5.
  Keycloak redirects directly to the caller's `return_to` URL after the
  broker flow completes; the caller polls
  `GET /v1/users/{id}/social-providers` to confirm the link landed. The
  callback endpoint is a Phase 6/12 addition once the Notifications module
  ships an email-based "we linked your Google account" confirmation.

## Anti-patterns (DO NOT)

- DO NOT call `CreateUserFederatedIdentity` from any user-facing endpoint.
  It is reserved for operator + migration paths.
- DO NOT skip the `session_state` / `issued_for` claims in the hash
  computation. Keycloak will reject the link if the hash does not match.
- DO NOT log the raw `state` token or the `nonce` — both are short-lived
  but neither is a secret-tier value; redact via the platform slog handler.
- DO NOT add a new IdP provider without an ADR. The MVP allowlist is
  Google, GitHub, Apple; the `Provider.Valid()` enum gate is the runtime
  enforcer.

## References

- AGENTS.md §8.3 (Identity endpoints), §18.7 (envelope encryption).
- foundations.md §8 (gocloak v14 anti-patterns).
- 06-identity-keycloak.md §5.5 (gocloak adapter signatures + research notes).
- Keycloak server administration guide — Identity Brokering chapter
  (https://www.keycloak.org/docs/26/server_admin/#identity_broker).
