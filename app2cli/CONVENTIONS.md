# app2cli Conventions

This document defines the default engineering conventions for `app2cli` based on the current repository, not the aspirational full product shape.

Current repository reality on April 3, 2026:

- Runtime: Node.js 20+ CLI
- Language: strict TypeScript with ESM
- Package manager: `pnpm`
- Quality gates: ESLint, `tsc --noEmit`, Vitest
- Current runtime surfaces:
  - CLI entrypoint in `src/cli/main.ts`
  - core schema, query, session, normalization, and artifact modules in `src/core/`
  - Playwright-backed web adapter in `src/adapters/web/`
- Not currently present:
  - backend or API server
  - frontend application
  - persistent database
  - auth or user sessions
  - workers, queues, or webhooks
  - implemented Android adapter

The default bar is correctness, determinism, security, and low-regret evolution. Keep the repo simple until the codebase creates a real need for more machinery.

## Architecture

### Default

- Treat this repo as a modular CLI, not a distributed system.
- Keep `src/core/` platform-agnostic and free of `src/cli/` and adapter imports.
- Keep `src/cli/` thin. Command parsing and output formatting belong there, not domain logic.
- Keep platform-specific extraction and action code inside `src/adapters/`.
- Prefer adding narrow modules over widening a single file with mixed responsibilities.

### Scale-up path

- Introduce `src/cli/commands/` once the CLI has multiple implemented command groups.
- Introduce a real `patterns/` registry only when rule-based pattern detection exists in code, not before.
- Introduce worker isolation only when browser or emulator execution becomes multi-tenant or remote.
- Introduce a service split only after a real always-on control plane exists. Until then, keep orchestration local to the CLI.

### Accepted exception

- A core module may re-export adapter-backed functionality when the re-export preserves the stable core import path and does not introduce reverse runtime coupling. `src/core/normalize/web-normalizer.ts` is the current example.

### Bad

- Adding command-specific parsing, schema validation, artifact persistence, and browser calls to one CLI file.
- Letting `src/core/` depend on Playwright, Appium, or Commander types.

## Code Organization

### Default

- One module should do one job and expose a small API.
- Keep schemas in `src/core/schema/` as the canonical contract for normalized output.
- Keep tests next to the source they cover.
- Prefer named exports over default exports.
- Prefer stable import paths through local `index.ts` files only when they reduce churn; do not add barrel files for one-off convenience.

### Scale-up path

- Split large modules once they have clearly separable responsibilities, not just because they crossed an arbitrary line count.
- Introduce fixture directories only when inline fixtures make tests hard to read.

### Accepted exception

- Small single-purpose files do not need an extra directory layer just to match a future target structure.

## Naming

### Default

- Use explicit names tied to the domain: `ArtifactWriter`, `PlatformAdapter`, `SnapshotSchema`.
- Prefer `verbNoun` for functions with side effects and `noun` or `describeNoun` for pure helpers.
- Use `*Schema` for Zod schemas and the same base name for inferred runtime types.
- Name checks, scripts, and CI jobs by outcome, not implementation detail.

### Bad

- `utils.ts`
- `helpers.ts`
- `doStuff()`

## Typing

### Default

- Keep strict TypeScript on.
- Add explicit return types on functions.
- Use `unknown` at trust boundaries and narrow deliberately.
- Use `interface` for object shapes and `type` only where unions or mapped types are the better fit.
- Validate system-boundary data with Zod before the rest of the system trusts it.

### Scale-up path

- Add branded identifiers only when plain strings create repeated mix-up bugs.
- Add separate transport DTOs only when there is a real external protocol boundary.

### Accepted exception

- Internal helper types can stay local to the module when exporting them would widen the public surface for no benefit.

## Error Handling

### Default

- Fail closed on ambiguous targets, malformed inputs, and unsupported states.
- Throw plain `Error` instances with specific messages unless the caller needs to branch on error kind.
- Preserve the first deterministic failure instead of trying multiple speculative fallbacks.
- Surface user-facing diagnostics in CLI code, not deep inside core modules.

### Bad

- Swallowing parser failures and returning partial output that looks valid.
- Catching errors only to replace them with less specific messages.

### Accepted exception

- Cleanup paths may suppress secondary close/disconnect failures after the primary work is already complete.

## Configuration

### Default

- Prefer checked-in declarative config for repo-wide policy.
- Keep command defaults local to the module that owns them.
- Validate new config at load time.
- Pin Node and toolchain expectations in repo metadata rather than tribal knowledge.

### Scale-up path

- Add environment-variable configuration only when the CLI truly needs runtime deployment variance.
- Add `.env.example` only when the repo actually consumes environment variables.

## Logging And Output

### Default

- The CLI owns user-facing output.
- Library modules return data or throw; they do not print.
- Use `console.error` or `console.warn` only for diagnostics that cannot be expressed through normal command output.
- Never log raw secrets, tokens, cookies, or full browser/session dumps.

## API And Schema Design

### Default

- Treat `src/core/schema/` as the compatibility contract.
- Add fields in a backward-compatible way whenever possible.
- Use `null` for platform-inapplicable fields that are part of the canonical schema.
- Keep locator data platform-specific under a shared envelope instead of flattening every platform detail into the top-level node.

### Scale-up path

- If the schema starts serving external consumers, document versioning explicitly and add compatibility tests before breaking it.

### Accepted exception

- Internal refactors may reshape intermediate adapter data as long as the normalized schema output remains stable.

## Security

### Default

- Treat file paths, URLs, raw page content, XML, and selector strings as untrusted inputs.
- Constrain filesystem writes to intended directories.
- Constrain URL handling to explicit supported schemes.
- Prefer exact selectors and validated locators over free-form execution.
- Persist only the artifacts required for reproducibility and debugging.

### Scale-up path

- If this becomes a remote or multi-tenant execution system, add per-job sandboxing, network egress policy, artifact encryption at rest, provenance checks for APKs, and stronger audit logging.
- If a service layer is introduced later, revisit SSRF, auth, authorization, and rate-limiting boundaries there. They are not current repo concerns because there is no server surface today.

### Accepted exception

- Test fixtures may contain synthetic URLs and HTML, but must not contain live secrets or production cookies.

## Testing

### Default

- New core logic requires unit tests.
- Security fixes require regression tests when they can be expressed locally.
- Integration tests are appropriate for adapter behavior that depends on Playwright or emulator state.
- Keep tests deterministic and offline by default.

### Bad

- Adding CI-only behavior with no local test path.
- Depending on external websites for unit tests.

## Performance And Scalability

### Default

- Prefer simple linear passes over premature caching.
- Optimize only where extraction or normalization proves hot.
- Keep artifact writes explicit and predictable.

### Scale-up path

- Introduce streaming or chunked artifact handling only when snapshot sizes make current writes materially expensive.
- Introduce concurrency controls only when multiple adapters or batch runs exist.

## Dependency Hygiene

### Default

- Reuse the existing toolchain before adding new packages.
- Prefer patch or minor upgrades for routine maintenance.
- Do not add a package when a small standard-library helper is clearer.
- Keep runtime dependencies narrower than dev dependencies.

### CVE policy

- Run `pnpm audit` when touching dependencies or before release-critical changes.
- Evaluate advisories by reachability and runtime exposure, not just severity labels.
- Prefer safe patch or minor upgrades first.
- If a vulnerability cannot be fixed immediately, document the reachability, current mitigation, and follow-up owner in the PR or issue.

## Deprecated Or Banned Patterns

- No `any`
- No `console.log`
- No adapter-to-adapter imports
- No unchecked filesystem writes from user-controlled path fragments
- No speculative fallbacks that hide deterministic failures
- No new dependency manager or duplicate task runner

## CI And Release Expectations

### Default

- CI must verify lint, typecheck, tests, and build.
- Required CI should be executable locally with checked-in commands.
- Network-dependent security checks should be explicit about being optional or scheduled if they are not deterministic enough for every required run.

### Scale-up path

- Add release automation only when the project is actually publishing packages or artifacts from CI.

## Git And Review

### Default

- One logical change per commit.
- Reviews should prioritize correctness, regressions, security boundaries, and missing tests.
- Avoid mixed refactors and feature work in the same change unless the refactor is required to land the fix safely.

## Documentation

### Default

- Update repo instructions when the default workflow changes.
- Update `CONVENTIONS.md` when a new default or scale-up decision is introduced.
- Document accepted exceptions where they are introduced instead of relying on memory.

### Current gaps

- The repo does not yet have a `README.md`.
- CI and audit expectations are now defined here and should stay aligned with checked-in automation.
