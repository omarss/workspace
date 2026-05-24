# ADR 002 — OpenAPI 3.1 authoring with overlay-downgrade for oapi-codegen

## Status
Accepted (2026-05-24).

## Context

- We author the API contract in OpenAPI 3.1 (full JSON Schema 2020-12, support
  for the `webhooks` section, native `type` arrays, `null` as a first-class
  type).
- `oapi-codegen` v2.7 does not natively support 3.1 (upstream issue #373, blocked
  on Go 1.26 / kin-openapi 3.1 support).
- `openapi-generator-cli` 7.22.0 (typescript-axios template) supports 3.1 with
  caveats on a handful of constructs.

## Decision

Apply an Overlay 1.0 transformation that down-converts the 3.1 spec to 3.0.3
before any code generator runs. Concretely:

1. Authors write 3.1 in `openapi/control-plane.yaml` and
   `openapi/data-plane.yaml`.
2. Spectral lints the 3.1 source directly (rules in `.spectral.yaml`).
3. `make openapi-check` applies `openapi/overlays/30-downgrade.yaml` and emits
   3.0.3 copies into `openapi/_generated/`.
4. `oapi-codegen` consumes the 3.0.3 copies via its `output-options.overlay`
   integration (see `.oapi-codegen-controlplane.yaml` and
   `.oapi-codegen-dataplane.yaml`).
5. `openapi-generator-cli typescript-axios` also reads from the 3.0.3 copies
   until the 3.1 path is verified end-to-end.

## Consequences

- Authors write 3.1, tooling sees 3.0 — keep an eye on 3.1-only constructs that
  the overlay cannot cleanly down-convert: `prefixItems`,
  `unevaluatedProperties`, `$dynamicRef`. These are banned in our spec until
  upstream issue #373 closes.
- Generated code under `internal/{controlplane,dataplane}/httpapi/` and
  `sdk/ts/**/` is checked in. CI fails on drift via `make openapi-diff-check`.
- Revisit when `oapi-codegen` merges native 3.1 support (track issue #373).
