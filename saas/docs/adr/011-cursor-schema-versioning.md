# ADR 011 — Cursor schema versioning

## Status

Accepted (2026-05-24, Phase 2).

## Context

AGENTS.md section 5.3 specifies opaque base64url-encoded JSON cursors with a
mandatory `v` field. Clients treat the cursor as opaque; the server reserves
the right to evolve the encoding.

When the cursor schema changes (e.g. adding a tie-breaker, switching the
keyset, including a sort signature), how should the server treat cursors
encoded under the old shape?

## Decision

- Bumping the cursor schema version returns **410 Gone** for any cursor
  encoded under an earlier version. Clients must drop the stored cursor
  and re-paginate from page 1.
- We do **not** attempt to re-interpret old cursors against the new schema
  — silent re-interpretation has caused real-world bugs (pages skipped or
  repeated, sort tuples swapped) in other platforms.
- The `Decode` function returns `ErrVersionMismatch` for any `v` mismatch;
  the handler translates that to 410 with a `cursor-gone` problem type.

The current cursor:

```text
base64url(json{"v":1,"k":"<created_at>","id":"<id>"})
```

is documented in `internal/platform/cursor/cursor.go` and exposed only to
the server — clients see an opaque string.

## Consequences

- Cursor evolution is straightforward but breaking. We expect to bump `v`
  on the order of once per year, only when adding a feature that justifies
  it (e.g. supporting a new sort axis).
- Mismatched cursors return 410 rather than 400/422 so client libraries
  can distinguish "this cursor was once valid but is now retired" from
  "this is malformed input".
- The handler returns a problem-details body with `type =
  https://saas.omarss.net/problems/cursor-gone`.

## Revisit

Reconsider when the platform first ships a v2 cursor schema (probably
when a list endpoint needs a secondary sort key beyond `created_at`).
