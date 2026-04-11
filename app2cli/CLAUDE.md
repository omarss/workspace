# app2cli

Open-source CLI tool that converts live web applications and Android APKs into structured, machine-readable UI representations.

Default engineering conventions and scale-up guidance live in `CONVENTIONS.md`. Read that file alongside this one before making repo-wide changes.

## Architecture

- **Web track**: Playwright + Chromium + CDP-backed semantic extraction
- **Android track**: Cuttlefish/Emulator + Appium + UiAutomator2 + adb
- **Shared CLI**: Commander-based CLI that works identically for both platforms
- **Common schema**: Both platforms normalize into one canonical JSON format

## Tech Stack

- TypeScript (strict mode)
- Node.js >= 20, ESM modules
- pnpm for package management
- Commander for CLI
- Zod for schema validation
- fast-xml-parser for Android XML parsing
- Vitest for testing
- ESLint with typescript-eslint strict + stylistic rules

## Project Structure

```
src/
  cli/           - CLI entry point and command definitions
    commands/    - one file per command group (web, android, inspect, etc.)
  core/          - platform-agnostic domain logic
    schema/      - Zod schemas for UI nodes, screens, sessions
    normalize/   - normalizers that produce canonical JSON from raw sources
    query/       - selector engine for querying UI nodes
    artifacts/   - artifact writer (screenshots, raw source, JSON)
    patterns/    - UI pattern recognition detectors
  adapters/      - platform-specific extraction and action clients
    web/         - Playwright/Chromium adapter, DOM extractor, a11y extractor
    android/     - Appium client, adb client, UiAutomator parser
```

## Development Commands

Always use the Makefile:

```bash
make install    # install dependencies
make build      # compile TypeScript
make lint       # lint (zero warnings)
make test       # run tests
make typecheck  # typecheck without emitting
make check      # lint + typecheck + test (run before every commit)
make dev        # run CLI in dev mode
make clean      # remove dist/
```

## Rules

- **Always run `make check` before committing.** Lint, typecheck, and tests must all pass.
- **Strict linting**: zero warnings tolerance, strict TypeScript, no `any`, explicit return types.
- **No console.log**: use `console.warn` or `console.error` for diagnostics, or use a proper logger.
- **Atomic commits**: one logical change per commit, lowercase messages under 50 chars.
- **No breaking changes** without explicit approval.
- **Prefer existing packages** over reinventing. Check npm before writing utilities.
- **Test core logic**: schemas, normalizers, query engine, pattern detectors must have tests.
- **UI tree first, pixels second**: never rely on screenshots as primary source when structured data is available.
- **Fail closed on ambiguity**: if the parser can't confidently determine the target, stop and report.
- **Keep extraction separate from action execution**: inspect and act are different components.
- **Adapter interface**: web and android adapters implement shared interfaces so the CLI doesn't care about platform.
- **No serverless for execution**: browsers and Android sandboxes run on dedicated workers, not Lambda/FaaS.
- **Security**: one sandbox per job, provenance mandatory for APKs, artifacts encrypted at rest in production.

## Schema Contract

Both platforms produce normalized JSON conforming to the canonical schema defined in `src/core/schema/`. The schema includes:
- Session metadata (id, platform, target, timestamp)
- Screen metadata (title, url/package/activity, dimensions)
- UI nodes (id, type, role, text, bounds, states, locators, hierarchy)
- Artifacts (screenshot path, raw source path, normalized source path)
- Recognized patterns (kind, confidence, evidence, semantic object refs)

## Design Principles

1. Normalize everything into one schema
2. Keep extraction separate from action execution
3. Persist every state transition (raw source, normalized source, screenshot, action log)
4. Pattern recognition is rule-based first, LLM only as secondary tie-breaker
5. Confidence policy: >= 0.95 safe for action, 0.85-0.94 safe for query only, < 0.85 fail closed
