# Phase 13 — Operator Realm + MFA + Step-Up Auth + Impersonation Tokens

> **Goal**: Import the Keycloak `operators` realm (separate from data-plane realms), enforce MFA via TOTP + WebAuthn, implement step-up auth for destructive actions (re-auth within 5 min required for upgrade/rollback/restore/purge/freeze-keys), wire IP allowlist enforcement at the operator JWT validator. Implement `POST /control/v1/deployments/{id}/impersonation-sessions` that mints a short-lived (≤15 min) data-plane JWT marked `actor_type=operator_impersonation`. Every request under that token is tagged in audit (Phase 10).
>
> **Why now**: 00-master.md puts MFA + impersonation here because Phase 11 control plane shipped operator endpoints with stub JWT; Phase 12e wired freeze-keys (the most dangerous endpoint) but step-up was a TODO. Phase 13 closes that gap. The §18.4 model — "A Data Plane token never satisfies a Control Plane endpoint" — was scaffolded in Phase 11; Phase 13 enforces it with real auth + audit.
>
> **What this phase does NOT do**: No SSO into operators realm (operators use local Keycloak users with TOTP/WebAuthn). No operator-to-operator delegation. No "break-glass" emergency token (a runbook concern). No automatic IP allowlist updates (operator manually edits).
>
> **Maps to AGENTS.md**: §18.4 (the entire section), §8.0 impersonation-sessions endpoint, §17.3 (operator-specific authz tests), §18.3 (audit list: operator login + impersonation). `01-foundations.md` §8 (gocloak, jwx, realm import).
>
> **Estimated subagent sessions**: 2-3 (one for realm + MFA flow + JWT verifier swap; one for step-up middleware + impersonation endpoint; one for tests + IP allowlist).

---

## Pre-flight

1. AGENTS.md §18.4, §8.0 (impersonation), §17.3, §18.3.
2. `01-foundations.md` §8 (gocloak + jwx + audience handling).
3. Phase 5 (`06-identity-keycloak.md`) — confirm JWKS cache pattern.
4. Phase 11 (`12-control-plane-skeleton.md`) — confirm the operator JWT verifier stub is in place.
5. CHECKPOINT 9 approved (a real Deployment is provisionable).

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Operator realm | Separate `operators` realm in Keycloak; clients: `saas-controlplane` (service account for the platform), `saas-operator-cli` (interactive PKCE for saasctl) | Single realm with role separation (refused per §18.4) |
| MFA mechanism | CONFIGURE_TOTP + webauthn-register both as default required actions on user create; either satisfies the AMR claim | TOTP only (refused — phishing-resistant WebAuthn matters); SMS (refused — not E2E secure) |
| Step-up window | 5 minutes (re-auth required within this window for destructive verbs) | Configurable per Deployment (refused for MVP — fixed) |
| Step-up verbs | upgrade, rollback, restore, purge, freeze-keys, impersonation-session create | Larger list (refused — adds friction); smaller (refused — purge is destructive) |
| Step-up signal | `acr` claim in the token; refreshed by re-auth; checked at handler entry | Custom header (refused — easier to forge); separate token (refused — UX worse) |
| IP allowlist | Per-operator `ip_allowlist` (CIDR list) enforced at the JWT validator; rejected with 403 + `ip-not-allowlisted` | Per-organization (refused — operators are individuals) |
| Impersonation token TTL | 15 min hard max; 5 min default; operator-supplied via `duration_seconds` request body | 1 hour (refused — too long for a destructive scope) |
| Impersonation audience | Data-plane realm of the target Deployment (`saas-data-<dep_id>`) with `acr=urn:saas:impersonation` | Generic (refused — audience binding is the point) |
| Impersonation scope | `actor_type=operator_impersonation` claim; every audit row under it carries the operator ID + the impersonation reason | Reduced scope (refused — operators sometimes need full surface for incident response) |
| Webauthn / TOTP enrollment UX | Operators enroll on first login via Keycloak's native pages; no custom flow | Custom (refused — Keycloak's are vetted) |

---

## Tasks

### 13.1 Operators realm JSON — `deploy/keycloak/realms/operators-realm.json`

```json
{
  "realm": "operators",
  "enabled": true,
  "displayName": "SaaS Operators",
  "defaultSignatureAlgorithm": "RS256",
  "requiredActions": [
    { "alias": "CONFIGURE_TOTP", "name": "Configure OTP", "providerId": "CONFIGURE_TOTP", "enabled": true, "defaultAction": true, "priority": 10 },
    { "alias": "webauthn-register", "name": "Register Security Key", "providerId": "webauthn-register", "enabled": true, "defaultAction": true, "priority": 20 }
  ],
  "authenticationFlows": [
    {
      "alias": "step-up-mfa",
      "description": "Step-up MFA for destructive actions (re-auth required within 5 min)",
      "providerId": "basic-flow",
      "topLevel": true,
      "builtIn": false,
      "authenticationExecutions": [
        { "authenticator": "auth-cookie",                "requirement": "ALTERNATIVE", "priority": 10 },
        { "authenticator": "identity-provider-redirector","requirement": "ALTERNATIVE", "priority": 20 },
        { "flowAlias": "step-up-mfa-forms",              "requirement": "ALTERNATIVE", "priority": 30 }
      ]
    }
  ],
  "clients": [
    {
      "clientId": "saas-controlplane",
      "name": "SaaS Control Plane Service Account",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": false,
      "serviceAccountsEnabled": true,
      "standardFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "secret": "REPLACE_AT_BOOTSTRAP",
      "attributes": { "use.refresh.tokens": "false" }
    },
    {
      "clientId": "saas-operator-cli",
      "name": "saasctl CLI (PKCE)",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": true,
      "standardFlowEnabled": true,
      "directAccessGrantsEnabled": false,
      "redirectUris": ["http://localhost:8765/callback", "http://127.0.0.1:8765/callback"],
      "webOrigins": ["+"],
      "attributes": {
        "pkce.code.challenge.method": "S256",
        "post.logout.redirect.uris": "+"
      }
    }
  ],
  "roles": {
    "realm": [
      { "name": "deployments.read",   "composite": false },
      { "name": "deployments.write",  "composite": false },
      { "name": "deployments.upgrade","composite": false },
      { "name": "deployments.rollback","composite": false },
      { "name": "deployments.restore","composite": false },
      { "name": "deployments.purge", "composite": false },
      { "name": "deployments.freeze","composite": false },
      { "name": "operators.read",     "composite": false },
      { "name": "audit.read",         "composite": false },
      { "name": "tenants.impersonate","composite": false },
      { "name": "operator-admin",     "composite": true,
        "composites": { "realm": ["deployments.read","deployments.write","deployments.upgrade","deployments.rollback","deployments.restore","deployments.purge","deployments.freeze","operators.read","audit.read","tenants.impersonate"] }
      }
    ]
  },
  "browserFlow": "step-up-mfa",
  "smtpServer": {
    "host": "mailhog",
    "port": "1025",
    "from": "noreply@omarss.net",
    "fromDisplayName": "SaaS Operators",
    "auth": "false"
  }
}
```

Import via Keycloak's `--import-realm` at boot. **Confidence/gap**: the step-up flow stanza shown is a sketch; Keycloak's actual built-in step-up flow is configured via Authentication → Flows in the admin UI. For MVP we use the built-in flow `browser` with the `Required Actions: CONFIGURE_TOTP + webauthn-register` set on every user. The 5-minute step-up window is enforced **server-side** in the platform (not in Keycloak) — see §13.4.

### 13.2 Operator inventory + IP allowlist storage

Already created in Phase 11 (`operator` table). Extend with MFA status:

`migrations/controlplane/000004_operator_mfa.up.sql`:

```sql
ALTER TABLE operator ADD COLUMN amr text[] NOT NULL DEFAULT '{}',     -- last successful AMR methods
ALTER TABLE operator ADD COLUMN last_step_up_at timestamptz,            -- managed via cache; this is a hint
ALTER TABLE operator ADD COLUMN kc_user_id text UNIQUE;
```

### 13.3 Swap operator JWT verifier — real

Phase 11 had a stub. Phase 13 wires the real verifier against the operators realm:

`cmd/controlplane/main.go`:

```go
opVerifier, err := auth.NewJWTVerifier(ctx,
    os.Getenv("OP_JWKS_URL"),     // https://localhost:8081/realms/operators/protocol/openid-connect/certs
    os.Getenv("OP_ISSUER"),       // https://localhost:8081/realms/operators
    "saas-control")
```

Update `internal/platform/auth/jwt.go` to:

- Parse `amr` claim (array of strings).
- Parse `acr` claim (string).
- Parse `auth_time` (Unix timestamp).
- Enforce `aud=saas-control` strictly (existing).

Add `Principal.AMR []string`, `Principal.ACR string`, `Principal.AuthTime time.Time`.

### 13.4 IP allowlist middleware

`internal/platform/auth/ip_allowlist.go`:

```go
func IPAllowlistMiddleware(repo OperatorRepo) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            p, ok := PrincipalFromContext(r.Context())
            if !ok { next.ServeHTTP(w, r); return }
            if p.ActorType != ActorOperator { next.ServeHTTP(w, r); return }
            op, err := repo.GetByID(r.Context(), p.ActorID)
            if err != nil { writeProblem(w, ErrUnauthorized); return }
            if len(op.IPAllowlist) == 0 { next.ServeHTTP(w, r); return }
            ip := parseClientIP(r)
            if !cidrAllowed(ip, op.IPAllowlist) {
                writeProblem(w, ErrIPNotAllowed); return
            }
            next.ServeHTTP(w, r)
        })
    }
}
```

Wired in control-plane chi chain AFTER the JWT verifier.

### 13.5 Step-up middleware

`internal/platform/auth/step_up.go`:

```go
const stepUpWindow = 5 * time.Minute

// RequireStepUp enforces that the principal has authenticated with a
// strong AMR (totp / webauthn) within the last stepUpWindow.
// Used as a route-level middleware on destructive endpoints.
func RequireStepUp() func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            p, ok := PrincipalFromContext(r.Context())
            if !ok { writeProblem(w, problem.TypeUnauthorized); return }
            if !p.HasStrongAMR() {
                writeProblem(w, problem.Problem{Type: problem.TypeStepUpRequired, Status: 403, Title: "Step-up authentication required"}); return
            }
            if time.Since(p.AuthTime) > stepUpWindow {
                writeProblem(w, problem.Problem{Type: problem.TypeStepUpRequired, Status: 403, Title: "Step-up window expired; re-authenticate"}); return
            }
            next.ServeHTTP(w, r)
        })
    }
}

// HasStrongAMR returns true if at least one of (otp, hwk, swk, mfa, webauthn,
// hwa, fpt, kba) appears in the amr array. Conservative; tighten later.
func (p Principal) HasStrongAMR() bool {
    strong := map[string]struct{}{"otp":{},"hwk":{},"swk":{},"mfa":{},"webauthn":{},"hwa":{},"fpt":{}}
    for _, m := range p.AMR { if _, ok := strong[m]; ok { return true } }
    return false
}
```

Wire on routes:

```go
r.Route("/control/v1/deployments/{deployment_id}", func(r chi.Router) {
    r.Use(auth.RequireScope("deployments.read"))
    r.Get("/", getDeployment)
    // Destructive endpoints:
    r.Group(func(r chi.Router) {
        r.Use(auth.RequireStepUp())
        r.Post("/upgrade",   upgradeDeployment)
        r.Post("/rollback",  rollbackDeployment)
        r.Post("/restore",   restoreDeployment)
        r.Post("/purge",     purgeDeployment)
        r.Post("/freeze-keys", freezeKeys)
        r.Post("/impersonation-sessions", startImpersonation)
    })
})
```

### 13.6 Impersonation endpoint

`/control/v1/deployments/{deployment_id}/impersonation-sessions` is already in Phase 11's OpenAPI. Implement the handler:

```go
func (h *Handler) StartImpersonationSession(ctx context.Context, req httpapi.StartImpersonationRequestObject) (httpapi.StartImpersonationResponseObject, error) {
    p, _ := auth.PrincipalFromContext(ctx)
    if !p.HasScope("tenants.impersonate") { return problem.Forbidden, nil }

    // Step-up is already enforced by middleware (RequireStepUp).
    dep, err := h.depRepo.Get(ctx, req.DeploymentID)
    if err != nil { return problem.NotFound, nil }

    duration := time.Duration(req.Body.DurationSeconds) * time.Second
    if duration == 0 { duration = 5 * time.Minute }
    if duration > 15 * time.Minute { duration = 15 * time.Minute }

    // Mint a data-plane JWT against the target Deployment's realm.
    token, err := h.tokenMinter.MintImpersonationToken(ctx, dep.ID, req.Body.TargetMemberID, p.ActorID, req.Body.Reason, duration)
    if err != nil { return nil, err }

    // Audit BEFORE returning the token.
    _ = h.events.Publish(ctx, "operator.impersonation_started", "", map[string]any{
        "deployment_id": dep.ID, "operator_id": p.ActorID,
        "target_member_id": req.Body.TargetMemberID, "reason": req.Body.Reason,
        "duration_seconds": int(duration.Seconds()),
    })
    return httpapi.StartImpersonationSession201JSONResponse{
        Token: token, ExpiresAt: time.Now().Add(duration),
    }, nil
}
```

`tokenMinter` uses gocloak's token exchange or a service-account token-issue path. For MVP local dev, the platform's `saas-controlplane` service account in the operators realm has the `urn:ietf:params:oauth:grant-type:token-exchange` grant enabled against the target data-plane realm. The exchange returns a token with:

- `aud = saas-data-<dep_id>`
- `tenant_id = <looked up from target_member_id>`
- `sub = <target_member_id>`
- `actor_type = operator_impersonation`
- `actor_id = <operator's id>` (added as a custom claim)
- `impersonation_reason = <reason>` (added as a custom claim)
- `acr = urn:saas:impersonation`
- `exp = now() + duration`

**Confidence/gap**: gocloak v14 has limited support for token exchange. The exact API call:

```go
res, err := kc.GetRequestingPartyToken(ctx, opSAToken, "operators", gocloak.RequestingPartyTokenOptions{
    Audience: gocloak.StringP("saas-data-" + depID),
    // ...
})
```

If gocloak doesn't expose token-exchange cleanly, fall back to a direct REST POST to Keycloak's `/realms/operators/protocol/openid-connect/token` endpoint with the `urn:ietf:params:oauth:grant-type:token-exchange` grant. The realm config grants the controlplane service account the right impersonation policies.

Verify token-exchange config via the Keycloak admin REST API during bootstrap.

### 13.7 Data-plane: accept operator-impersonation tokens

`internal/platform/auth/jwt.go` (data plane) accepts tokens whose:

- `iss` = the data-plane realm
- `aud` = the data-plane realm's client (`saas-data-<dep_id>`)
- `actor_type = operator_impersonation` → set `Principal.ActorType = ActorOperatorImpersonation`
- `tenant_id` populated as normal
- AMR / step-up are NOT required at the data plane (operator already proved at control plane)

The data-plane audit subscriber (Phase 10) checks `actor_type` and includes it in audit metadata, plus the `actor_id` and `impersonation_reason` claims.

### 13.8 Operators realm bootstrap

`make operators-realm-import` target:

```make
operators-realm-import:
	docker compose exec keycloak /opt/keycloak/bin/kc.sh import \
		--file /opt/keycloak/data/import/operators-realm.json \
		--override true
	docker compose restart keycloak
```

After import, the operator runs a one-time setup:

```bash
$ saasctl operator create --email omar@omarss.net --name "Omar"
# Prompts for IP allowlist (CIDR), then sends an email with the Keycloak login link.
```

The operator's first login at the Keycloak page enrolls TOTP and WebAuthn (required actions). saasctl's interactive flow runs a local web server on `:8765` for the PKCE callback.

### 13.9 saasctl login + token persistence

`saasctl operator login` runs the OAuth2 + PKCE flow:

1. Generate `code_verifier` + `code_challenge` (S256).
2. Open browser to `https://localhost:8081/realms/operators/protocol/openid-connect/auth?...`.
3. Operator authenticates + completes MFA challenge.
4. Keycloak redirects to `http://localhost:8765/callback?code=...`.
5. saasctl exchanges code for tokens + persists to `~/.saas/credentials.json` (mode 0600).
6. Subsequent commands read the token; refresh via OIDC refresh until expiry.

Step-up flow: when a destructive endpoint returns 403 + `step-up-required`, saasctl re-runs the auth flow (forcing AMR re-prompt via `acr_values=mfa max_age=0`) and retries.

### 13.10 Tests

`step_up_test.go`:

- Token with no `amr` → 403
- Token with `amr=[pwd]` only (no MFA) → 403
- Token with `amr=[pwd,otp]` + auth_time within 5 min → 200
- Token with `amr=[pwd,otp]` + auth_time 6 min ago → 403 + `step-up-required`
- Token with `amr=[webauthn]` + fresh → 200

`ip_allowlist_test.go`:

- Operator with empty allowlist → no enforcement
- Operator allowlist `10.0.0.0/24`, request from `10.0.0.5` → 200
- Operator allowlist `10.0.0.0/24`, request from `192.168.1.1` → 403
- Operator allowlist mixed v4 + v6 → both honored

`impersonation_test.go`:

- Token exchange returns a data-plane token with correct audience + actor_type
- Data plane accepts the token + populates Principal.ActorType=operator_impersonation
- Audit row carries `actor_type`, `actor_id`, `impersonation_reason`
- Token expiry rejected
- Duration > 15 min capped at 15 min

`integration_test.go`:

- Full flow: operator login → saasctl deployment upgrade → step-up prompt → retry → success → audit row exists

### 13.11 §17.3 matrix update

Every operator endpoint test now includes:

| Test | Assert |
|---|---|
| Operator login (PKCE) → token issued | 200 + JWT with `amr` + `acr` |
| Token from operators realm against data-plane endpoint | 401 (aud mismatch) |
| Operator without MFA → call destructive | 403 + step-up-required |
| Operator outside IP allowlist | 403 + ip-not-allowlisted |
| Impersonation: operator without `tenants.impersonate` scope | 403 |
| Impersonation: data-plane audit shows operator id + reason | matched |
| Impersonation token expiry past TTL | 401 |

### 13.12 Commits

```bash
git add deploy/keycloak/realms/operators-realm.json Makefile
git commit -m "import operators realm with mfa and step up"

git add migrations/controlplane/000004_operator_mfa.up.sql
git commit -m "extend operator with mfa fields"

git add internal/platform/auth/jwt.go internal/platform/auth/step_up.go internal/platform/auth/ip_allowlist.go
git commit -m "wire amr acr step up and ip allowlist"

git add internal/controlplane/deployments/handler.go
git commit -m "require step up on destructive endpoints"

git add internal/controlplane/operators/ cmd/controlplane/main.go
git commit -m "implement operator login and impersonation"

git add cmd/saasctl/
git commit -m "saasctl operator login pkce flow"
```

---

## Verification checklist

```bash
# 1. Realm imported.
$ make operators-realm-import
$ curl -s http://localhost:8081/realms/operators/.well-known/openid-configuration | jq .issuer
# Expected: http://localhost:8081/realms/operators

# 2. Build + lint + tests.
$ make build && make lint && make test && make test-int

# 3. Operator login via PKCE.
$ ./bin/saasctl operator create --email omar@omarss.net --name "Omar"
# Browser opens → Keycloak login → MFA enrollment → success.
$ ./bin/saasctl operator login
# Browser opens → tokens persisted to ~/.saas/credentials.json
$ cat ~/.saas/credentials.json | jq .access_token | head -c 40

# 4. Read endpoint works without step-up.
$ ./bin/saasctl deployment list
# Expected: lists deployments

# 5. Destructive endpoint requires step-up.
$ ./bin/saasctl deployment upgrade <dep_id> --image v0.3.2
# Expected: 403 step-up-required; saasctl re-prompts auth; retry succeeds

# 6. IP allowlist.
$ ./bin/saasctl operator update omar@omarss.net --ip-allowlist 10.0.0.0/24
$ # From a non-matching IP:
$ curl -i https://control.saas.omarss.net/control/v1/deployments -H "Authorization: Bearer $OP_TOK"
# Expected: 403 ip-not-allowlisted

# 7. Impersonation E2E.
$ ./bin/saasctl impersonation start <dep_id> --target-member member_... --reason "incident #42"
# Prints a token + expiry.
$ IMP=...
$ curl https://prod.mvp.saas.omarss.net/v1/tenants -H "Authorization: Bearer $IMP" | jq
# Expected: 200; subsequent audit row shows actor_type=operator_impersonation

$ psql -d saas_mvp_prod -c "SELECT actor_type, actor_id, metadata FROM audit_event ORDER BY chain_sequence DESC LIMIT 1;"
# Expected: actor_type=operator_impersonation, actor_id=op_..., metadata.impersonation_reason="incident #42"

# 8. Token expiry.
$ sleep 901 && curl https://prod.mvp.saas.omarss.net/v1/tenants -H "Authorization: Bearer $IMP"
# Expected: 401 token expired

# 9. AMR check.
$ # Use a token where amr=["pwd"] only (configure a test client without MFA).
$ curl -i https://control.saas.omarss.net/control/v1/deployments/<id>/purge -H "Authorization: Bearer $PWD_TOK"
# Expected: 403 step-up-required
```

---

## Anti-pattern guards

- **NEVER** issue an operator JWT without `amr` in the token. Keycloak emits it automatically when MFA is configured; if absent, the verifier rejects.
- **NEVER** accept a data-plane token at the control plane (aud mismatch is the hard rule).
- **NEVER** mint an impersonation token longer than 15 min.
- **NEVER** skip the audit `operator.impersonation_started` emit BEFORE returning the token.
- **NEVER** allow a destructive endpoint without `RequireStepUp` in the chi chain. The middleware order matters: JWT verifier → scope → step-up → handler.
- **NEVER** trust `X-Forwarded-For` without `realip` middleware seating it. The control-plane host nginx sets `X-Real-IP`; the platform reads via `chi/middleware/realip`.
- **NEVER** persist operator tokens beyond their TTL. saasctl's credentials file holds refresh tokens; refresh keeps access tokens current.
- **NEVER** allow `tenants.impersonate` scope on a data-plane realm token. Only operators-realm tokens carry it. The data-plane validator strips on entry.

---

## Open questions

1. **WebAuthn attestation requirements.** Default: any platform/cross-platform authenticator accepted. Tighten to `direct` attestation + a specific transports list for high-security operators? Out of MVP.
2. **TOTP issuer name.** Default: `SaaS Operators`. Confirm.
3. **PKCE callback port.** Default: 8765. Configurable via `~/.saas/config.yaml`. Confirm.
4. **Step-up window adjustable per operator.** Default: fixed at 5 min. v1.

---

## Phase 13 — Definition of done

- [ ] `deploy/keycloak/realms/operators-realm.json` imported via `make operators-realm-import`
- [ ] `migrations/controlplane/000004_operator_mfa.up.sql` applied
- [ ] `internal/platform/auth/{jwt,step_up,ip_allowlist}.go` complete + tests
- [ ] Control-plane chi chain wires JWT → scope → step-up (where applicable) → IP allowlist
- [ ] saasctl operator login (PKCE) + auto-refresh + re-auth prompt on step-up
- [ ] Impersonation endpoint mints a data-plane JWT with correct audience + claims
- [ ] Data plane accepts operator_impersonation tokens; audit records actor_type + actor_id + reason
- [ ] §17.3 matrix passes for all operator endpoints
- [ ] All Phase 2-12e tests still green
- [ ] PR template, `ready` label, CI green

---

End of Phase 13. Next: `15-go-sdk.md`.
