# Problem catalogue

This directory holds the RFC 9457 Problem Details type fragments referenced by
`internal/platform/problem/types.go`. Every constant `TypeXxx` in that file
MUST have a matching `<slug>.yaml` file here describing the semantics,
required fields, and example payload.

The `make openapi-check` round-trip lints these fragments via spectral; CI
fails when a constant exists without a fragment, or vice versa.

## Adding a new problem type

1. Add the URI constant to `internal/platform/problem/types.go`.
2. Create `openapi/problems/<slug>.yaml` with fields:
   - `description` — RFC 9457 `title` candidate
   - `status` — default HTTP status
   - `example` — full example body
3. Update `openapi/data-plane.yaml` (or `control-plane.yaml`) responses to
   `$ref` the slug.
4. Add the catalogue entry to `CONVENTIONS.md` §3.

ADR 002 — OpenAPI 3.1 authoring with overlay-downgrade — governs how these
fragments compose with the main specs.
