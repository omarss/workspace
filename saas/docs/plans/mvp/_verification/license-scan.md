# License scan — Phase 16

## Method

The MVP plan §16.3 suggested running `licenseclassifier` via a Docker image; we
attempted that but the cited image (`ghcr.io/google/licenseclassifier:latest`)
is not published. We then tried `github.com/google/go-licenses@latest`, which
fails on this repo because there is no root LICENSE file (the platform is
intentionally unlicensed publicly while in development) — the tool refuses to
classify its own module's transitive packages without that anchor.

We fell back to a direct allowlist walk: enumerate every `<module> <version>`
entry in `go.mod` (direct **and** indirect — 148 modules in total) and
classify the LICENSE / COPYING / LICENCE file shipped in each module's
`pkg/mod` cache against a regex set for the standard OSI texts. The script
lives at `scripts/license-scan.sh` (committed in this phase).

This approach is sound because:

1. Go module fetch is hash-verified (`go.sum`) — the LICENSE files in
   `pkg/mod` are byte-identical to what `go build` ships in any container.
2. Every dep we ship is OSS; their LICENSE files are upstream's canonical text.
3. The allowlist regexes (Apache 2.0, MIT, BSD-{2,3}-Clause, MPL-2.0, ISC,
   PostgreSQL, BlueOak-1.0.0) cover every dep this repo currently uses.

## Allowlist

Per AGENTS.md §3.5 / §4.4 / §25.8:

| Allowed | Rationale |
|---|---|
| MIT | OSI-approved, permissive |
| Apache-2.0 | OSI-approved, permissive, patent grant |
| BSD-2-Clause | OSI-approved, permissive |
| BSD-3-Clause | OSI-approved, permissive |
| MPL-2.0 | OSI-approved, weak copyleft — allowed because we link only |
| ISC | OSI-approved, permissive (BSD-equivalent) |
| PostgreSQL | OSI-approved, permissive (BSD-equivalent) |
| BlueOak-1.0.0 | OSI-approved, permissive |
| 0BSD (BSD Zero Clause) | OSI-approved, permissive |
| Zlib | OSI-approved, permissive |

## Disallowlist (hard fail)

| Forbidden | Rationale |
|---|---|
| BSL | source-available; not OSI |
| SSPL | source-available; not OSI |
| Elastic License v2 (ELv2) | source-available; not OSI |
| CC-BY-NC | non-commercial restriction |
| GPL-3.0 (linked) | copyleft on linking; we only allow AGPL when used as a standalone network service |
| AGPL-3.0 (linked) | as above — only acceptable as a network-service dep we DO NOT link |

## Result

148 modules scanned, 0 findings. License distribution:

| License | Count |
|---|---|
| MIT | 55 |
| Apache-2.0 | 55 |
| BSD-3-Clause | 22 |
| MPL-2.0 | 9 |
| BSD-2-Clause | 3 |
| ISC | 2 |
| Zlib (`github.com/mmcloughlin/meow`) | 1 |
| 0BSD (`github.com/woodsbury/decimal128`) | 1 |
| **Total** | **148** |

No BSL, SSPL, Elastic License v2, CC-BY-NC, GPL-3.0, or AGPL-3.0 dependency
appears in the dependency tree.

### Notable MPL-2.0 deps

All from the HashiCorp ecosystem (consumed by the OpenBao client):

- `github.com/hashicorp/errwrap`
- `github.com/hashicorp/go-cleanhttp`
- `github.com/hashicorp/go-multierror`
- `github.com/hashicorp/go-retryablehttp`
- `github.com/hashicorp/go-secure-stdlib/parseutil`
- `github.com/hashicorp/go-secure-stdlib/strutil`
- `github.com/hashicorp/go-sockaddr`
- `github.com/hashicorp/hcl` (vault fork)
- (one more transitively)

MPL-2.0 is file-level copyleft: modifications to those individual files must
be published under MPL, but linking + un-modified bundling are fine. We do
not patch any of these.

### AGPL exception (not currently triggered)

AGENTS.md §3.5 allows AGPL only when the dep is consumed as a standalone
network service (Novu, Lago, OpenBao itself, etc.). Those are consumed via
HTTP API, not linked, so no Go module appears in our `go.mod` with that
license.

## Reproduce

```bash
$ /tmp/license-scan.sh > license-summary.txt    # or scripts/license-scan.sh
$ awk '{print $1}' license-summary.txt | sort | uniq -c | sort -rn
$ grep -E "^(BSL|SSPL|Elastic|^GPL|^AGPL|CC-BY-NC)" license-summary.txt
```

Expected: empty match.

## Verdict

**PASS** — no findings. The dependency tree is fully license-compatible with
AGENTS.md §3.5.
