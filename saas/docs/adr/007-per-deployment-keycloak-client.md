# ADR 007 — Per-Deployment Keycloak client vs single client with audience-resolve

## Status

Accepted (2026-05-24, Phase 5).

## Context

Each Deployment is an isolation boundary (AGENTS.md §18.1). A platform User
in Deployment A must never present a token whose `aud` claim satisfies
Deployment B's audience check (§18.4). Keycloak gives us two ways to model
this:

1. **Single global client** `saas-data` with an "audience-resolve" protocol
   mapper that emits `aud=saas-data-<dep_id>` based on the user's
   `deployment_id` attribute.
2. **Per-Deployment client** `saas-data-<dep_id>` with its own
   `aud=saas-data-<dep_id>` mapper hard-coded into the client config.

The choice impacts how isolation is enforced, how rotation works, and what
deletion looks like when a Deployment is purged.

## Decision

**Per-Deployment client (option 2).**

For Phase 5 (this phase), local dev uses a single client `saas-data-local`
in a single realm `saas-data-local`. Phase 12 introduces the real
per-Deployment realm + client pair, created by the control-plane provisioner
at deployment time via gocloak.

## Consequences

### Positive

- **Mechanical audience enforcement.** The token's `aud` is hard-bound to
  the issuing client; a Deployment-A token presented to Deployment-B's data
  plane fails the audience check at the JWT verifier (foundations §8). No
  protocol-mapper logic to audit.
- **Per-Deployment secret rotation.** Compromising one client's secret has
  no blast radius into other Deployments — each client carries its own
  credentials in OpenBao KV.
- **Clean delete.** Removing a Deployment removes its client; no orphan
  attributes lingering on a shared client.
- **Per-Deployment IdP brokers.** Google / GitHub / Apple OAuth credentials
  are scoped to the client + realm pair, so adding a provider to one
  Deployment cannot leak into another.

### Negative

- **Client count scales linearly.** Keycloak handles thousands of clients
  per realm; we are unlikely to hit a wall, but the operator now has to
  understand the per-Deployment topology.
- **Provisioning complexity.** The control-plane provisioner must create
  the client + audience mapper + IdP brokers at deployment time. The
  alternative (one shared client) was cheaper to provision but compromised
  isolation.

### Phase 5 deviation

Phase 5 ships against a single shared `saas-data-local` realm + client for
local development only. The production code path (per-Deployment realm,
per-Deployment client, audience-mapper on the client) is built out in
Phase 12 alongside the real provisioner. The single-realm choice is
deliberately temporary; isolation tests in Phase 5 mock the audience
verification because the per-Deployment audience does not yet exist.

## Alternatives considered

| Alternative | Rejected because |
|---|---|
| Single client with audience-resolve mapper | Mapper logic is a moving part to audit; secret rotation has global blast radius. |
| Per-Deployment realm with a shared client | Same audience-resolve problem; loses per-Deployment IdP isolation. |
| Per-Tenant client (finer-grained) | Tenants share a Deployment by design; finer-grained clients add ops cost with no isolation benefit. |

## References

- AGENTS.md §18.1 (isolation boundaries), §18.4 (operator MFA / audience).
- foundations.md §8 (Keycloak via gocloak v14).
- 06-identity-keycloak.md §5.8 (realm import template).
