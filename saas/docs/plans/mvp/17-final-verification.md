# Phase 16 — Final Verification (§26 DoD per Endpoint + §17.3 Matrix + §17.4 Provisioning)

> **Goal**: Walk every shipped endpoint against AGENTS.md §26 (Definition of Done) and §17.3 (authorization matrix) and §17.4 (provisioning tests). Run a license scan on all dependencies (confirm no BSL/SSPL/Elastic crept in). Run `make openapi-diff-check` to confirm no generated-code drift. Confirm no Surveys code present (out of MVP and out of v1 — §28 non-goal). Confirm no Newsletters MVP code (v1 roadmap only; only the spec stub may exist). Confirm AGENTS.md reflects scope changes (Notifications + Social + BYOD + saasctl init + BYOK). Final go/no-go review with the user.
>
> **Why now**: Last phase of the MVP plan. After this phase the §15 hard cut is verifiable end-to-end. Producing a punch list of v1 roadmap items closes the loop.
>
> **What this phase does NOT do**: No new features. No bug-fix sweep beyond what verification surfaces. Bugs found here are tracked as separate PRs.
>
> **Maps to AGENTS.md**: §15 MVP scope, §15.1 v1 roadmap, §15.2 Never (without ADR), §17.3, §17.4, §26 DoD, §27 breaking-change policy, §28 non-goals.
>
> **Estimated subagent sessions**: 2 (one for matrix sweep + license scan; one for AGENTS.md update + punch list + final go/no-go).

---

## Pre-flight

1. AGENTS.md §15, §15.1, §15.2, §17.3, §17.4, §26, §27, §28.
2. All Phase 1-15 verification checklists were green at landing time. Re-run all `make` targets here.
3. The latest `main` (post-Phase 15) is the verification target.

---

## Decisions to surface before coding

None for this phase — it's verification, not feature work. If the sweep surfaces a bug, decide per bug whether to fix here (small) or open a follow-up PR (large).

---

## Tasks

### 16.1 Re-run the global verification matrix

```bash
$ make compose-down
$ docker volume rm $(docker volume ls -q --filter label=com.docker.compose.project=saas) 2>/dev/null
$ make compose-up
$ ./bin/saasctl init        # fresh end-to-end bootstrap

# 1. Build + lint + tests + integration
$ make build
$ make lint
$ make test
$ make test-int
$ make contract-test
$ make openapi-check

# 2. SDK builds.
$ make sdk-ts && (cd sdk/ts/data-plane && npm install && npx tsc --noEmit)
$ make sdk-go && (cd sdk/go && go build ./...)

# 3. Provisioning §17.4 matrix.
$ go test -run TestProvisioning -v ./internal/controlplane/provision/sequence/...

# 4. Authorization §17.3 matrix per module.
$ go test -run "TestTenants_AuthZ|TestUsers_AuthZ|TestOrganizations_AuthZ|TestAuthorization_AuthZ|TestAPIKeys_AuthZ|TestAudit_AuthZ|TestNotifications_AuthZ|TestDeployments_AuthZ" -v ./internal/...

# 5. Operator MFA + step-up + impersonation.
$ go test -run "TestStepUp|TestIPAllowlist|TestImpersonation" -v ./internal/...
```

Every command must exit 0. Any failure is captured and triaged below.

### 16.2 §26 DoD applied per endpoint

For each endpoint listed in §8, verify the 12 §26 items hold. Maintain a checklist file `docs/plans/mvp/_verification/endpoint-dod.md` (created in this phase) with one row per endpoint and a per-item checkbox.

Endpoints in scope (from §8):

| Plane | Endpoint | Group |
|---|---|---|
| Data | GET/POST/PATCH/DELETE /v1/tenants[/{id}] | Tenants |
| Data | GET/POST/PATCH/DELETE /v1/users[/{id}] + disable/enable/reset-password/verify-email | Identity |
| Data | GET/POST/DELETE /v1/users/{id}/social-providers[/{provider}] + GET /v1/social/callback | Social |
| Data | GET/POST/PATCH/DELETE /v1/notification-channels[/{id}] + rotate-credentials | Notifications |
| Data | GET/POST /v1/notification-workflows | Workflows |
| Data | POST /v1/notifications/send; GET /v1/notifications/{id} | Notifications |
| Data | GET/POST/PATCH/DELETE /v1/tenants/{id}/organizations[, /v1/organizations/{id}] | Organizations |
| Data | GET/DELETE /v1/organizations/{id}/members[/{id}] | Members |
| Data | GET/POST/DELETE /v1/organizations/{id}/invitations[, /v1/invitations/{id}]; POST /v1/invitations/{id}/accept | Invitations |
| Data | GET/POST/PATCH/DELETE /v1/tenants/{id}/roles[, /v1/roles/{id}]; GET /v1/permissions; POST/DELETE /v1/members/{id}/roles[/{id}]; POST /v1/authorization/check + batch-check | RBAC |
| Data | GET/POST/PATCH/DELETE /v1/tenants/{id}/api-keys[, /v1/api-keys/{id}]; POST /v1/api-keys/{id}/rotate + revoke | API keys |
| Data | GET /v1/tenants/{id}/audit-events; GET /v1/audit-events/{id}; POST /v1/audit-events/export | Audit |
| Control | GET/POST/PATCH/DELETE /control/v1/deployments[/{id}] + upgrade/rollback/restart/restore/purge/freeze-keys | Deployments |
| Control | GET /control/v1/deployments/{id}/{revisions,health,logs,audit-integrity}; POST /control/v1/deployments/{id}/impersonation-sessions | Deployments admin |
| Control | GET/POST/DELETE /control/v1/deployments/{id}/domains[/{id}]; POST /control/v1/deployments/{id}/domains/{id}/verify | BYOD |
| Control | GET /control/v1/audit-events; GET /control/v1/operators | Control audit + operators |

Per-row checklist:

```markdown
| Endpoint | OAS | Impl | Unit | Integration | Contract | Authz matrix | RLS | Audit | Idemp | ETag | Otel | SDK TS | SDK Go | Recipe |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |
```

Fill in for every endpoint. Empty cells = gap; produce a follow-up issue.

### 16.3 License scan

`make license-scan`:

```make
license-scan:
	$(GO) list -m -json all | \
	    docker run --rm -i ghcr.io/google/licenseclassifier:latest \
	    > licenses.json
	jq '.[] | select(.License != "MIT" and .License != "Apache-2.0" and .License != "BSD-2-Clause" and .License != "BSD-3-Clause" and .License != "MPL-2.0" and .License != "PostgreSQL" and .License != "ISC")' licenses.json
```

Output: any package whose license is NOT in the allowlist. Expected: empty (no findings). If any appear, they must be replaced or have an ADR (per §3.5).

Confirm no BSL/SSPL/Elastic License v2/Apache 2.0+CC/source-available licenses anywhere.

Tools: also run `licensei check --threshold approve` if available; otherwise `golicense` or `go-licenses`.

For Node deps (none direct; only the docker-run-based tools in the Makefile — image licenses are out of scope for Go-side scan).

### 16.4 Generated code drift

```bash
$ make openapi-check
$ git diff --exit-code
```

Expected: clean. If anything diffed: someone edited generated files by hand; revert and surface as a follow-up.

### 16.5 Surveys + Newsletters confirmation

Search the codebase:

```bash
$ git grep -i "survey" -- . ':!docs/' ':!AGENTS.md'
# Expected: empty (or only test fixtures named after the word, in which case verify intent).

$ git grep -i "newsletter" -- . ':!docs/' ':!AGENTS.md' ':!openapi/data-plane.v1-roadmap.yaml'
# Expected: empty.
```

Confirm `openapi/data-plane.v1-roadmap.yaml` exists with Newsletters stub but no implementation. Confirm `internal/dataplane/newsletters/` does NOT exist.

If either feature surfaces real code, file a removal PR before the final review.

### 16.6 AGENTS.md update (scope changes documented inline)

Per 00-master.md, the scope changes need to land in AGENTS.md proper:

| Change | Where to update |
|---|---|
| Promote Notifications to MVP | §4.4 ("Notifications" moved from v1 to MVP); §8.7.3 removed; §8.7 (new) data-plane notifications endpoints; §15 (MVP list adds Notifications); §15.1 SMS/WhatsApp listed under v1; §18.3 adds "notification send" to the audit list; §21 adds "send-notification" workflow |
| Add Social login to MVP | §8.3 adds `/v1/users/{id}/social-providers` endpoints; §12.2 module description updated; §17.3 adds cross-tenant social-link tests; §18.3 adds user.social_linked/.unlinked; §21 adds "link-social-provider" workflow |
| Add BYOD to MVP | §6.5 mentions BYOD domain attach; §8.0 adds `/control/v1/deployments/{id}/domains/*` endpoints; §12.1 module description updated; §15 MVP list adds BYOD |
| Add saasctl init wizard to MVP | §15 MVP list adds "saasctl init wizard"; §21 adds setup recipe |
| Add BYOK vendor creds to MVP | §18.7 enumerates Notification channel creds as required BYOK; §15 MVP adds BYOK vendor creds |
| Add Newsletters to v1 roadmap | §15.1 inserts "Newsletters (broadcast via Novu; opt-in; GDPR/PDPL unsubscribe)" |
| Add Surveys to non-goals | §28 inserts "surveys / NPS module (Product Builder feature, not platform plumbing)" — already present per earlier scope review |

Make these edits in this phase. Re-run `make openapi-check` after every edit that touches OpenAPI references.

### 16.7 CONVENTIONS.md final pass

Confirm every Phase 3-15 entry is still accurate. In particular:

- §10 PII persistence convention (Phase 4 + extensions in Phases 5, 6, 7, 9, 10)
- §3 Service method signatures (every tenant-bound method takes ctx, tenantID, ...)
- §13 (new section if needed) Operator MFA and step-up patterns
- §x KV path map (Phase 12d → consumed by Phases 5, 6, 7, 9, 10, 11, 13)

If any drift, fix in this phase.

### 16.8 Punch list of v1 roadmap items

Author `docs/v1-roadmap.md` consolidating §15.1:

```markdown
# v1 Roadmap (post-MVP)

In order:

1. **Newsletters** — broadcast via Novu; subscriber lists; opt-in; GDPR/PDPL unsubscribe; reuses Phase 6 channel + workflow infra. (User-requested priority.)
2. **SMS / WhatsApp channels** — extends notifications with Twilio + WhatsApp Cloud API.
3. **Plans, Subscriptions, Billing** — Lago wrapper; §8.7.1.
4. **Entitlements + Limits** — feature flagging on the entitlement axis; §8.7.2.
5. **Files** — MinIO/S3 wrapper; presign upload/download; §8.7.4.
6. **Webhooks** — own outbox + delivery worker; signature verification helpers in SDKs; §8.7.5.
7. **Feature Flags** — OpenFeature + a local provider; §8.7.6.
8. **Analytics** — PostHog integration; §8.7.7.
9. **Support (Chatwoot)** — §8.7.8.
10. **Multi-replica policy sync** — Redis watcher for Casbin (ADR 005).
11. **Multi-replica rate limiter** — Redis-backed; replaces Phase 9 in-process bucket.
12. **OpenBao dynamic database secrets engine** — opt-in per Deployment.
13. **Cloud KMS auto-unseal** — ADR 006 production path.
14. **Per-Deployment Keycloak realms (real)** — Phase 5 used a single shared realm; v1 wires per-Deployment.
15. **Email change flow** — Phase 5 deferred.
16. **Audit async export** — Phase 10 sync-only; ≥ 1MB triggers async with polling.
17. **Audit external chain anchor** — weekly Sigsum-style transparency log push.
```

### 16.9 Final go/no-go review

The subagent presents:

1. The §26 DoD coverage table (every endpoint × 12 items).
2. The §17.3 matrix coverage (every endpoint × 8 cases).
3. The §17.4 provisioning matrix (14 cases).
4. License scan: clean.
5. Generated code drift: none.
6. Surveys / Newsletters: confirmed absent / v1-only stubs.
7. AGENTS.md scope-change diffs applied.
8. CONVENTIONS.md updated.
9. v1 roadmap published.
10. Any open follow-up issues.

The user gives a final go (proceed to MVP release) or no-go (specific punch list to address).

### 16.10 Optional MVP release tag

If go: tag `mvp-v1.0.0` on the repo (Phase 16 commit), publish a release notes summary in `docs/release-notes/mvp.md`, push the tag. Operator artifacts:

- `bin/controlplane`, `bin/dataplane`, `bin/migrate`, `bin/saasctl` (build via `make build`).
- Docker images: `localhost:5000/saas/controlplane:mvp-v1.0.0`, `:mvp-v1.0.0` for dataplane.
- SDK tags: `sdk/ts@v1.0.0`, `sdk/go@v1.0.0`.

### 16.11 Commits

```bash
git add docs/plans/mvp/_verification/endpoint-dod.md docs/plans/mvp/_verification/coverage.md
git commit -m "add final verification matrices"

git add AGENTS.md
git commit -m "update agents md for mvp scope changes"

git add CONVENTIONS.md
git commit -m "final pass on conventions"

git add docs/v1-roadmap.md
git commit -m "publish v1 roadmap"

git add docs/release-notes/mvp.md   # only if go/no-go = go
git commit -m "mvp release notes"
```

---

## Verification checklist

```bash
# 1. Full lint + test cycle clean.
$ make compose-down && make compose-up && ./bin/saasctl init
$ make build && make lint && make test && make test-int && make contract-test && make openapi-check

# 2. License scan clean.
$ make license-scan
# Expected: empty list outside allowlist

# 3. Generated code drift: none.
$ make openapi-check && git status --porcelain
# Expected: empty

# 4. Provisioning matrix.
$ go test -run TestProvisioning -v ./internal/controlplane/provision/sequence/...

# 5. Per-module §17.3 matrices.
$ go test -run "_AuthZ$" -v ./internal/...

# 6. SDK builds (TS + Go).
$ make sdk-ts && cd sdk/ts/data-plane && npm install && npx tsc --noEmit
$ make sdk-go && cd sdk/go && go build ./...

# 7. Surveys / Newsletters check.
$ git grep -i "survey" -- ':!docs/' ':!AGENTS.md' ':!docs/plans/'
$ git grep -i "newsletter" -- ':!docs/' ':!openapi/data-plane.v1-roadmap.yaml' ':!AGENTS.md' ':!docs/plans/'
# Expected: empty

# 8. AGENTS.md scope changes applied.
$ grep -A1 "Notifications" AGENTS.md | head -10        # Notifications listed under §15 MVP
$ grep "social-providers" AGENTS.md                     # social login endpoints documented
$ grep "domains" AGENTS.md | head -5                    # BYOD endpoints documented
$ grep "saasctl init" AGENTS.md                         # init wizard in §21

# 9. v1 roadmap published.
$ wc -l docs/v1-roadmap.md
# Expected: ~30 lines, 17 items

# 10. End-to-end smoke: a fresh operator can land a deployment in < 10 minutes.
$ time ./bin/saasctl init
# Expected: < 600 seconds
```

---

## Anti-pattern guards

- **NEVER** add new features in this phase. Verification only.
- **NEVER** declare a §26 DoD item green without running the check. Visual confirmation is not enough.
- **NEVER** mark an endpoint complete on the matrix when the §17.3 matrix is missing a case.
- **NEVER** suppress license scan findings with an ignore-rule unless an ADR explains the exception.
- **NEVER** edit generated code to make the drift check pass. Regenerate from the spec.
- **NEVER** sign off without a green CI run on the latest commit. Local greens are insufficient.

---

## Open questions

1. **Release tag scheme.** Default: `mvp-v1.0.0`, then `mvp-v1.0.1` for patches, `mvp-v1.1.0` for additive changes. Confirm with user.
2. **Release artifacts.** Default: built binaries + Docker images + SDK module tags. Confirm.
3. **Post-release retro.** Default: schedule a retro one week after tag; surface the surface-bugs vs deep-bugs ratio. Out of MVP plan but tracked.
4. **What if a §26 item fails for a small number of endpoints?** Default: open targeted PRs per gap; do not block the release if the gaps are documented + the user explicitly accepts the residual risk.

---

## Phase 16 — Definition of done

- [ ] All Phase 1-15 verification checklists re-run green
- [ ] §26 DoD matrix complete for every endpoint in §8 (12 items × N endpoints)
- [ ] §17.3 authorization matrix complete for every tenant-bound endpoint
- [ ] §17.4 provisioning matrix (14 cases) green
- [ ] License scan: no BSL/SSPL/Elastic License v2/source-available; AGPL only as standalone network service
- [ ] Generated code drift: none
- [ ] Surveys: confirmed absent; v1 roadmap does NOT include it (§28 non-goal)
- [ ] Newsletters: only the v1-roadmap.yaml stub; no MVP code
- [ ] AGENTS.md updated with the 7 scope changes (Notifications, Social, BYOD, saasctl init, BYOK, Newsletters→v1, Surveys→non-goal)
- [ ] CONVENTIONS.md current
- [ ] `docs/v1-roadmap.md` published with 17 items in priority order
- [ ] `docs/plans/mvp/_verification/` artifacts committed
- [ ] User signs off on the final go/no-go
- [ ] Optional: `mvp-v1.0.0` tag pushed if go

---

End of Phase 16. End of plan.
