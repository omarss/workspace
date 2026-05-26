# ADR 019 — Operators realm + MFA + step-up + IP allowlist + impersonation

- **Status**: Accepted (Phase 13)
- **Date**: 2026-05-26
- **Deciders**: platform team
- **Supersedes**: scaffolded portions of ADR 007 (per-Deployment Keycloak client) for the operator path
- **Relates to**: AGENTS.md §18.3 (audit list), §18.4 (operator auth model), §8.0 (impersonation endpoint), CONVENTIONS.md §14 (audit), 01-foundations.md §8 (gocloak + jwx)

## Context

The control-plane API serves operators (us — the platform team) and only us. Operators provision Deployments, run destructive lifecycle ops (upgrade / rollback / purge / freeze-keys), and occasionally need to impersonate a tenant for incident response. The blast radius of an operator compromise is the entire fleet, so the threat model is materially different from the data-plane tenant-bound API:

1. **No self-service**: operators are vetted humans, not API consumers.
2. **No SSO**: a compromised upstream IdP would be catastrophic; we run our own realm.
3. **MFA-mandatory**: a stolen password alone must not be sufficient.
4. **Step-up**: even with MFA, destructive ops require a *fresh* re-auth — a token left open in a stale terminal must not be usable to purge a Deployment.
5. **IP allowlist**: defense in depth against credential theft from unmanaged endpoints.
6. **Impersonation**: must be tagged in audit on *every* downstream request, not just at session start.

Phase 11 scaffolded the operator JWT verifier shape (`internal/platform/auth/operatorjwt`) and the operator inventory table; Phase 12e built the host provisioner that the destructive endpoints actually drive. Phase 13 closes the auth gap.

## Decision

### Separate Keycloak realm

The operators live in a dedicated Keycloak realm `operators` (audience `aud=saas-control`), distinct from every per-Deployment data-plane realm. The audience binding is enforced at the JWT verifier *before any other claim is read*; a data-plane token cannot satisfy a control-plane endpoint and vice versa.

Realm-level controls:

- `registrationAllowed = false`, `resetPasswordAllowed = false`, `editUsernameAllowed = false`. Operators are created out-of-band by an existing operator_admin via the saas-controlplane service account.
- `bruteForceProtected = true`, failureFactor 5, `permanentLockout = false` (an attacker cannot DoS an operator by burning passwords from the public auth page).
- `accessTokenLifespan = 900s` (15 min) — matches the impersonation token ceiling.
- `ssoSessionMaxLifespan = 28800s` (8h) — absolute cap on a session.
- Password policy: 12-char minimum + complexity + 90-day rotation + argon2id (Keycloak's default since v22).

### MFA: TOTP AND WebAuthn enrolment on first login

Both are added as `defaultAction` required actions on the realm. The operator sees two screens on first login: register a TOTP authenticator AND register a security key (or platform authenticator). Either satisfies the runtime MFA check — the operator can use whichever is closer at hand.

The browser flow (`browser-with-mfa`) is a copy of the built-in browser flow with a REQUIRED MFA step (`auth-otp-form` ALTERNATIVE `webauthn-authenticator`) inserted after `auth-username-password-form`. Tokens emitted by this flow carry `amr` containing `pwd` + (`otp` | `hwk`).

### Step-up: 5-minute window enforced server-side

Per AGENTS.md §18.4. The destructive control-plane endpoints (upgrade / rollback / purge / freeze-keys / impersonation-sessions / detach-domain) are wrapped in `operatorjwt.RequireStepUp`, which checks:

1. The principal has at least one strong AMR (`otp` / `hwk` / `swk` / `mfa` / `webauthn` / `hwa` / `fpt`).
2. The `acr` claim equals `gold` (LoA 2 per the realm-level `acr.loa.map`).
3. `now - auth_time < 5 min`.

On failure, the middleware returns 403 + problem-type `step-up-required` with a `kc_acr=gold max_age=0` hint embedded in `detail`. saasctl reads the hint and re-runs the OIDC auth flow with `max_age=0` to force a fresh credential prompt.

We enforce this server-side rather than relying on Keycloak's `max_age` because:

- Keycloak's `max_age` only applies *at the IdP authorization step*; it cannot retroactively refuse an already-issued token.
- The platform is the authoritative gate; Keycloak is the freshness source.
- Tests can clock-inject a stale `auth_time` without needing a running Keycloak.

### IP allowlist per operator

`operator.ip_allowlist text[]` holds zero or more CIDRs. Empty == no restriction (the default — operators tighten their own allowlists after enrolment). The `IPAllowlistMiddleware` is wired AFTER the JWT verifier so it has a `Principal` to look up against. Trusted-proxy handling: only the homelab nginx's CIDR is allowed to set `X-Real-IP`; from any other source the header is ignored (the chi RealIP CVE rationale).

### Impersonation: platform-signed (not Keycloak)

`POST /control/v1/deployments/{deployment_id}/impersonation-sessions` mints a short-lived data-plane JWT signed by the *control plane*, not Keycloak. Claims:

```text
iss                       saas-controlplane
aud                       saas-data-<deployment_id>
sub                       <operator_id>
actor_type                operator_impersonation
actor_id                  <operator_id>
actor_email               <operator_email>
tenant_id                 <target tenant_id>
target_member_id          <member_id, optional>
impersonation_session_id  impses_<ulid>
reason                    <free-text up to 256 chars>
iat / exp / nbf           seconds since epoch
```

Hard ceilings: duration ≤ 15 min, default 5 min. The session is inserted in `impersonation_session` before the JWT is signed; the row's `ended_at` column lets the data-plane verifier refuse a revoked token even though it has not yet hit `exp`.

We picked self-signed over Keycloak token-exchange because:

- gocloak v14's token-exchange surface is incomplete (per Phase 13 plan §13.6 confidence/gap note).
- Per-target-realm exchange-policy plumbing would have to be replicated per Deployment.
- The audience binding (`saas-data-<dep_id>`) is the actual security gate, and we control it directly.

The data-plane auth middleware (Phase 14+) adds an impersonation-token branch alongside the existing API-key + Keycloak-JWT paths. When `actor_type == operator_impersonation`, every downstream audit row carries the operator_id + impersonation_reason in metadata.

### Audit

Three new audited event types (already in CONVENTIONS.md §14.1):

- `operator.login` — emitted on first JWT verify per session
- `operator.impersonation_started` — emitted BEFORE the JWT is returned to the operator
- `operator.impersonation_ended` — emitted on explicit end-of-session OR passive expiry

Phase 10's audit subscriber map already includes these types; Phase 13 wires the emit sites.

## Consequences

### Positive

- The 8-layer tenant-isolation invariant is preserved: operator tokens cannot satisfy a data-plane endpoint, and impersonation tokens cannot leak into the control plane.
- Destructive ops require *fresh* MFA every 5 min — a forgotten open terminal can't purge anything.
- IP allowlist gives a soft hardware-binding for operators on managed endpoints.
- Impersonation is fully audited and revocable.

### Negative

- Operator UX is friction-heavy by design: re-auth every 5 min during incident response. We accept this trade.
- Self-signed impersonation tokens require the control plane to hold a signing secret that the data plane trusts. Compromise of the control plane host therefore breaks impersonation isolation — same blast radius as Postgres app-role compromise, so not new risk.
- The 5-min step-up window is hard-coded for MVP. Configurable per operator (or per Deployment) is a v1 ask.

### Open items (v1+)

- WebAuthn attestation tightening (direct attestation + transports allowlist for high-security operators).
- Per-operator step-up window override.
- Operator-to-operator impersonation delegation (rejected for MVP).
- Break-glass emergency token (runbook, not code).

## Alternatives considered

- **Single Keycloak realm with role separation**: rejected — audience-based isolation is stronger than role-based; misconfigured tokens would have a wider blast radius.
- **TOTP-only MFA**: rejected — WebAuthn / FIDO2 is phishing-resistant; TOTP is not. We support both so operators can use whichever they have.
- **SMS MFA**: rejected — not end-to-end secure, SS7 attack surface.
- **Keycloak token-exchange for impersonation**: rejected — gocloak v14 support is incomplete; per-Deployment policy plumbing scales poorly.
- **Per-Deployment impersonation key**: rejected for MVP — Phase 14+ feature. The audience binding limits blast radius enough to defer.
- **Step-up via re-prompt at Keycloak only**: rejected — Keycloak's `max_age` is best-effort at auth time; it cannot refuse an already-issued token.
