# Agent Guidelines for app2cli

## Overview

app2cli converts web apps and Android APKs into structured UI representations. AI coding agents working on this repo must follow these guidelines.

## Before Making Changes

1. Read `CLAUDE.md` and `CONVENTIONS.md` for project rules, current architecture, and default engineering decisions
2. Run `make check` to verify the project is in a clean state
3. Understand the component you're modifying by reading related files first

## Architecture Boundaries

### Adapters (`src/adapters/`)
- Platform-specific code lives here
- Web adapter wraps Playwright/Chromium
- Android adapter wraps Appium/adb
- Adapters implement shared interfaces defined in `src/core/`
- Never import adapter code from another adapter

### Core (`src/core/`)
- Platform-agnostic domain logic
- Schemas, normalizers, query engine, pattern detectors
- Must not import from `src/adapters/` or `src/cli/`
- This is the most tested layer

### CLI (`src/cli/`)
- Thin layer that wires commands to core + adapters
- Minimal logic — delegates to core and adapters
- Uses Commander for command definitions

## Coding Standards

- TypeScript strict mode, ESM modules
- Explicit return types on all functions
- No `any` type — use `unknown` and narrow
- No `console.log` — use structured output or `console.error` for diagnostics
- Prefer `interface` over `type` for object shapes
- Use Zod for runtime validation at system boundaries
- Use `type` imports for type-only imports

## Testing

- Test files live next to source: `foo.ts` -> `foo.test.ts`
- Use Vitest with `describe`/`it`/`expect`
- Core logic must have unit tests
- Adapters are tested with integration tests (may need real Playwright/Appium)
- Golden fixture tests: store expected JSON outputs and compare

## Commit Protocol

1. Make your change
2. Run `make check` (lint + typecheck + test)
3. Fix any failures
4. Commit with a lowercase message under 50 chars
5. One logical change per commit

## Common Tasks

### Adding a new CLI command
1. Create command file in `src/cli/commands/`
2. Register it in `src/cli/main.ts`
3. Wire it to the appropriate core/adapter functions
4. Add tests

### Adding a new pattern detector
1. Create detector in `src/core/patterns/detectors/`
2. Implement the `PatternDetector` interface
3. Register it in the pattern registry
4. Add golden fixture tests with expected pattern matches

### Adding a new schema field
1. Update Zod schema in `src/core/schema/`
2. Update both web and android normalizers
3. Update tests
4. Ensure backward compatibility or get approval for breaking change

### Modifying an adapter
1. Check if the change should be in the adapter interface (core) or implementation (adapter)
2. If interface changes, update both web and android implementations
3. Add integration tests
