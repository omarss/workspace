# ADR 015 — Bring-Your-Own-Domain: DNS TXT verification + multi-server_name + per-domain cert

## Status

Accepted (Phase 11, 2026-05-25).

## Context

Per the 2026-05-24 scope-change in `docs/plans/mvp/00-master.md`, each
Deployment may attach N custom domains (BYOD). The control plane must verify
ownership BEFORE nginx + certbot touch host state. Two verification approaches
were on the table:

1. **DNS TXT record** at `_saas-verify.<domain>` containing a token issued
   by the control plane at attach time.
2. **HTTP-01 challenge** — operator points the domain at the platform first,
   then certbot does the standard ACME http-01 dance.

(2) requires the domain to point at the platform IP before we can prove
ownership. Many BYOD orgs cannot flip DNS + cert + nginx atomically (DNS TTL,
existing CNAME records, third-party CDN in front, ...). The race window where
the domain points at the platform but no cert is installed is a public-facing
500 page on the operator's brand. (1) decouples ownership proof from cutover.

A second axis is HOW the verification value is generated:

| Option | Pro | Con |
|---|---|---|
| Random 24-byte token, stored in DB        | Operator can rotate by re-issuing | DB is the source of truth — recovery from DB loss requires re-verification |
| HMAC(deployment_id, domain) with per-Dep secret | Stateless verify — token is deterministic from inputs | HMAC key must live somewhere with a stable provenance (OpenBao KV) |

The plan (12-control-plane-skeleton.md §11.5) goes with HMAC-bound tokens.
The HMAC key is the per-Deployment secret stored in OpenBao KV at
`secret/data/<dep_id>/byod_hmac_key` (Phase 12d creates the KV entry; Phase 11
uses an in-memory placeholder).

## Decision

1. **Verification method**: DNS TXT.
   - Record name: `_saas-verify.<domain>`
   - Record value: `saas-verify=<token>` where `token` is
     `hex(HMAC-SHA256(deployment_id || ":" || domain, byod_hmac_key))`.
   - The 24-byte HMAC-SHA-256 output gives 192 bits of effective entropy —
     well above the 128-bit floor that resists brute-force token guessing.
2. **Verification call**: `POST /control/v1/deployments/{id}/domains/{dom_id}/verify`
   does a synchronous DNS lookup via Go's `net.DefaultResolver.LookupTXT`,
   uses `crypto/subtle.ConstantTimeCompare` against the expected value,
   updates the row to `verified` or `failed` accordingly, and emits a
   `deployment.domain_verified` outbox event.
3. **Cert issuance** (Phase 12a, not Phase 11): once `verified`, the
   controlplane appends the domain to the per-Deployment nginx vhost
   `server_name` and runs `sudo certbot --nginx -d <domain> --non-interactive
   --agree-tos -m <ops_email>` to obtain an LE cert. ACME challenge type:
   HTTP-01 (the domain now points at the platform; LE webroot under
   `/var/www/letsencrypt`). DNS-01 was rejected for MVP because it requires
   each BYOD customer to integrate with their own DNS provider's API.
4. **Per-Deployment domain limit**: 5 (configurable via
   `Deployment.metadata.byod_limit`). Lets's Encrypt's 50-cert/week limit
   applies per registered domain, so 5 BYOD certs sit well under any single
   customer's allotment.
5. **Cert shape**: per-domain (one cert per `server_name` entry).
   Wildcard certs apply only to the platform zone `*.saas.omarss.net`;
   BYOD never uses wildcard.

## Consequences

### Positive
- Operator can verify ownership BEFORE the cutover; no race window where
  the domain points at the platform but no cert is installed.
- Multiple BYOD domains map to one Deployment's data plane (one vhost,
  multiple `server_name`s; certbot expands the cert SAN list).
- HMAC-bound tokens are stateless w.r.t. verification — DB loss does not
  invalidate previously-issued tokens.
- Constant-time compare blocks timing-oracle attacks on the token.

### Negative
- BYOD customers must understand DNS basics. Documented in the Phase 15
  recipe.
- The per-Deployment HMAC key is a long-lived secret in OpenBao. If
  rotated, all unverified domains must re-issue a token (verified ones
  stay verified).
- DNS resolution at verify time depends on the platform's DNS resolver
  reaching the operator's authoritative zone. Behind a captive DNS resolver
  (corporate proxy, restrictive geofence) this can fail.

### Out of scope for Phase 11
- Daily re-check of unverified domains (controlplane polls only on
  `POST /verify`). Phase 12a's destroy reconciler may add a re-check tick.
- Renewal: certbot's own systemd timer handles renew. Phase 12a wires the
  post-renew hook that rewrites the vhost if SAN list changes.
- DNSSEC-aware verification (RFC 4034). MVP relies on the resolver's
  AD bit if present.

## Anti-patterns

- **Never** store the BYOD token in the DB as plaintext alongside an
  HMAC-based scheme; either choose stateful (token in DB) or stateless
  (HMAC) but not both, otherwise rotation semantics get ambiguous.
- **Never** allow a BYOD domain that is a subdomain of `*.saas.omarss.net`.
  The attach endpoint rejects with 422; the regex check is layered with
  the DB constraint.
- **Never** issue real certs from Phase 11. Phase 12a does that, AFTER
  CHECKPOINT 4 review.
- **Never** call the LookupTXT verify path with a user-supplied resolver.
  The default resolver is the only one used; arbitrary resolver injection
  would let a malicious operator spoof a verification.
