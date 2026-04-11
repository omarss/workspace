# Feedback

## Review Basis

- Baseline checks passed: `make check` completed successfully with 25 test files passing and 225 tests passing, with 2 skipped.
- I also did targeted repros for specific behaviors:
  - `pnpm tsx src/cli/main.ts android run --app-id com.example.app`
  - `pnpm tsx -e "import { queryBestMatch } from './src/core/query/index.ts'; ..."`
  - `node -e "const { join } = require('node:path'); ..."`
- I did not run a live Playwright browser session, a live Android device/emulator flow, or Docker images during this review.

## Scope

This review covered:

- CLI command correctness and contract consistency
- session and state lifecycle
- artifact persistence and replay durability
- APK acquisition and Android launch flow
- query and stable-ID behavior
- secret handling and redaction integration
- docs/implementation consistency where the docs describe current behavior

This review did not attempt to fully certify:

- live browser automation against real sites
- live device automation against real APKs
- performance under large snapshots
- container/runtime packaging behavior
- long-running or concurrent multi-user execution

## Findings

1. **High: `session delete` can escape the session directory and target arbitrary JSON files relative to the repo.**
   
   Evidence: `SessionStore.filePath()` directly does `join(this.dir, \`\${id}.json\`)` with no validation in `src/core/session-store.ts:191-193`, and `session delete` passes user input straight through in `src/cli/commands/session.ts:45-52`. The path behavior is exploitable: `path.join(".app2cli/sessions", "../../package")` resolves to `package.json`, which I confirmed with `node -e`.
   
   Affected scope:
   - `app2cli session delete`
   - internal `SessionStore` methods `get`, `touch`, `deactivate`, `delete`, and `save`
   - any future feature that accepts session IDs from user input or from untrusted disk state

   Clear example:
   - `app2cli session delete ../../package`
   - current path resolution turns that into `package.json`
   - the command then calls `rm(..., { force: true })` on that resolved path

   Impact: `app2cli session delete ../../package` would target `package.json`. The same unsanitized path construction also affects `get`, `touch`, `deactivate`, and `save` if those methods are ever exposed to user-controlled IDs.
   
   Why this matters:
   - this is not only a “bad path hygiene” issue
   - it is a direct filesystem write/delete boundary with user-controlled input
   - the current implementation can operate outside `.app2cli/sessions`

   Recommendation: validate session IDs as single safe path segments and enforce a resolved-path-under-root check like the artifact writer already does.

2. **High: the documented multi-command CLI workflow does not actually work across separate `app2cli` invocations.**
   
   Evidence: the README advertises `web open` followed by `inspect`, `query`, `click`, and `type` as separate commands in `README.md:32-65`. The implementation keeps runtime state only in the in-memory singleton `cliState` in `src/cli/state.ts:10-99`. `src/cli/main.ts:49-52` then always calls `cliState.cleanup()` on `beforeExit`, which disconnects the adapter and clears nodes, snapshot, session ID, and recorder before the process ends. A separate `SessionStore` exists in `src/core/session-store.ts`, but none of the runtime commands wire into it. I also reproduced the practical effect: a fresh `app2cli inspect` invocation immediately throws “No active session”.
   
   Affected scope:
   - `inspect`
   - `query`
   - `click`
   - `type`
   - `screenshot`
   - `export`
   - `session list/cleanup/delete` consistency with actual runtime state

   Clear example:
   1. run `app2cli web open https://example.com/login`
   2. let the process exit normally
   3. run `app2cli inspect`
   4. actual result: the second command starts in a fresh process with empty `cliState` and throws “No active session”

   Expected vs actual:
   - expected from README: a persisted session or resumable active context
   - actual implementation: only ephemeral in-process state, destroyed at process exit

   Impact: the primary UX described in the README is currently impossible. `session list/cleanup/delete` operate on a persistence layer that the actual `open`/`inspect`/`query`/`action` commands never populate.
   
   Why this matters:
   - this is the main top-level product flow shown to users
   - the issue is structural, not cosmetic
   - tests passing does not cover it because the gap is in command/process boundaries

   Recommendation: either implement real persisted session rehydration across commands or change the CLI model and documentation to a single-process interactive/session command.

3. **High: `android run` does not satisfy its advertised contract.**
   
   Evidence: the command and README both promise “acquire, install, and launch” in `src/cli/commands/android.ts:86-87` and `README.md:58-59`, `README.md:211-226`.
   
   Evidence: the `--app-id` and `--play-url` paths are guaranteed to fail in the default CLI. `acquireApk()` only builds a provider chain from local-file plus custom providers in `src/core/apk/pipeline.ts:62-86`; it never instantiates `FdroidProvider`, and the CLI does not expose any provider selection or `enabledProviders` wiring in `src/cli/commands/android.ts:88-107`. I reproduced this directly: `pnpm tsx src/cli/main.ts android run --app-id com.example.app` fails with “No APK providers available”.
   
   Evidence: even the `--apk` path does not launch the installed app. `android run` passes `acquisition.apkPath` into `AndroidClient.connect()` in `src/cli/commands/android.ts:114-120`. `AndroidClient.connect()` installs targets ending in `.apk`, but only launches targets that are not APK paths in `src/adapters/android/appium-client.ts:30-45`. So the code installs the APK, waits two seconds, and then inspects whatever app was already foreground.
   
   Evidence: for local APKs, `resolvePackageName()` returns `null`, and `acquireApk()` substitutes `"unknown"` in `src/core/apk/pipeline.ts:41-42`, so the session/provenance is incomplete even on the best current path.
   
   Affected scope:
   - `android run --apk`
   - `android run --app-id`
   - `android run --play-url`
   - README/API contract for APK acquisition
   - any downstream logic that relies on accurate Android session target/package metadata

   Clear examples:
   - `pnpm tsx src/cli/main.ts android run --app-id com.example.app`
     - actual result: fails immediately with “No APK providers available”
   - `app2cli android run --apk ./app.apk`
     - actual code path: install APK, do not launch package, inspect current foreground state

   Expected vs actual:
   - expected: acquire APK, install APK, determine package, launch app, then inspect that app
   - actual: only local file acquisition works by default, and even that path does not perform the launch step

   Impact: the flagship Android “all-in-one” flow is either guaranteed to fail or guaranteed not to launch the requested app.
   
   Why this matters:
   - this is a direct completeness gap in a prominently documented command
   - users will reasonably trust this path because the help text and README both present it as supported
   - the current implementation can silently inspect the wrong app after install

   Recommendation: make `android run` resolve a real package name, install the APK, and then explicitly launch that package/component; wire an actual default/provider-configured acquisition path for `--app-id` and `--play-url`.

4. **High: typed secrets are logged, replayed, and echoed in cleartext, despite the repo already having redaction utilities.**
   
   Evidence: `type` writes the exact text to stdout in `src/cli/commands/action.ts:163-166`. The action log persists `input` verbatim in `src/cli/commands/action.ts:225-248`. Replay persists `input: params.text` verbatim in `src/core/replay/recorder.ts:71-86` and writes JSONL/JSON in `src/core/replay/recorder.ts:113-138`.
   
   Evidence: the repo already contains `src/core/redact.ts` and a redaction-capable `ArtifactWriter` in `src/core/artifacts/writer.ts:13-18`, `29-37`, `132-137`, but the CLI always constructs `ArtifactWriter` without redaction settings in `src/cli/commands/web.ts:89`, `src/cli/commands/android.ts:132`, `src/cli/commands/inspect.ts:84`, and `src/cli/commands/action.ts:203`, `247`.
   
   Affected scope:
   - terminal output from `type`
   - action logs (`actions.jsonl`)
   - replay logs (`replay.jsonl`, `replay.json`)
   - any artifact directory shared in CI, support bundles, or debugging sessions

   Clear examples:
   - `app2cli type --query "field labeled password" "MySecret123!"`
   - current behavior includes:
     - terminal output: `typed into <node>: "MySecret123!"`
     - action log entry with `"input": "MySecret123!"`
     - replay step with `"input": "MySecret123!"`

   Impact: passwords, OTPs, tokens, and personal input can leak to terminal history, replay files, and action logs. This is a real security/privacy problem, not just a documentation gap.
   
   Why this matters:
   - the repo already recognizes this class of risk and has redaction helpers
   - the problem is therefore not “missing feature work”; it is that the sensitive boundary is currently not wired up
   - this affects both local developer usage and any shared artifact workflow

   Recommendation: never echo raw typed input by default, and enable redaction end-to-end for action logs and replay artifacts.

5. **Medium: saved `source.json` snapshots are internally inconsistent because artifact paths are backfilled only after the file is written.**
   
   Evidence: `ArtifactWriter.writeAll()` writes screenshot/raw source/normalized JSON concurrently in `src/core/artifacts/writer.ts:144-164`. The normalized JSON branch receives the snapshot before its `artifacts` field has been updated. Callers then mutate `snapshot.artifacts = artifactPaths` only after `writeAll()` resolves in `src/cli/commands/web.ts:91-107`, `src/cli/commands/android.ts:134-153`, and `src/cli/commands/inspect.ts:65-95`.
   
   Affected scope:
   - `web snapshot`
   - `android run`
   - `inspect --save`
   - any future feature that reads `source.json` expecting self-contained artifact references

   Clear example:
   1. build a snapshot with `artifacts: { screenshot: null, rawSource: null, normalizedSource: null }`
   2. call `writeAll(...)`
   3. `source.json` is serialized from the still-null artifact object
   4. only afterward is `snapshot.artifacts` updated in memory

   Expected vs actual:
   - expected: `source.json` should describe the final persisted snapshot, including artifact paths
   - actual: `source.json` can be missing the very paths it is meant to reference

   Impact: the in-memory snapshot returned to the user and the persisted `source.json` on disk can disagree about where the screenshot/raw source/normalized output actually live.
   
   Recommendation: write screenshot/raw source first, populate `snapshot.artifacts`, and only then persist the normalized snapshot JSON. Add a regression test that reads `source.json` and asserts it contains the final artifact paths.

6. **Medium: exact-ID queries broke when stable hashed node IDs were introduced.**
   
   Evidence: stable IDs are now generated as `n_<hash>_<index>` in `src/core/stable-id.ts:18-34`, `52-85`. But `parseQuery()` still only recognizes exact IDs matching `^n_\\d+$` in `src/core/query/selector-engine.ts:136-150`. I reproduced this directly with a synthetic node ID `n_deadbeef_0`; `queryBestMatch()` returned `null`.
   
   Affected scope:
   - `app2cli query <node-id>`
   - any automation or docs that expect IDs emitted by inspect/query output to be round-trippable
   - internal consistency between query resolution and action resolution

   Clear example:
   - node ID emitted by the current system: `n_deadbeef_0`
   - `queryBestMatch(nodes, "n_deadbeef_0")` returns `null`
   - direct action resolution still accepts IDs based on `startsWith("n_")` in `src/cli/commands/action.ts:21-32`

   Expected vs actual:
   - expected: “inspect -> copy ID -> query/click/type by ID” should work consistently
   - actual: query-by-ID only supports the old sequential format

   Impact: copy-pasting an ID from inspect output into `app2cli query <id>` no longer works, even though direct action resolution still accepts any ID starting with `n_` in `src/cli/commands/action.ts:21-32`.
   
   Recommendation: update exact-ID parsing to accept the actual stable ID format, and refresh tests/docs so query-by-ID covers hashed IDs.

7. **Medium: replay provenance is inconsistent between `click` and `type`.**
   
   Evidence: `click` preserves target resolution metadata and passes `score` and `matchedBy` into replay in `src/cli/commands/action.ts:107-118`. `type` resolves the node but throws that metadata away before calling `recordType()` in `src/cli/commands/action.ts:138-151`, `177-187`.
   
   Evidence: the replay schema expects this metadata in `src/core/replay/types.ts:13-24`, `src/core/replay/recorder.ts:71-86`, and the README says replay captures confidence score and match strategy in `README.md:239-250`.
   
   Affected scope:
   - replay auditing
   - debugging of failed `type` actions
   - parity between action types

   Clear example:
   - `click --query "button named sign in"` records decision metadata
   - `type --query "field labeled email" "user@example.com"` currently records the input text but not the confidence or matcher details that selected the target

   Impact: typed actions are materially less auditable than click actions, even though the rest of the system says the provenance should be present.
   
   Recommendation: carry the resolved `score` and `matchedBy` through `type` exactly the way `click` already does.

8. **Low: several CLI numeric options are parsed but never validated, so bad input degrades into confusing downstream behavior.**
   
   Evidence: raw `parseInt()` is used with no validation in `src/cli/commands/web.ts:35-40`, `src/cli/commands/android.ts:21-25`, `src/cli/commands/query.ts:39-44`, and `src/cli/commands/session.ts:38-41`.
   
   Affected scope:
   - `web open --width/--height`
   - `android boot --timeout`
   - `query --limit`
   - `session cleanup --purge-days`

   Clear examples:
   - `app2cli query --limit nope "button"` produces `parseInt("nope", 10) -> NaN`, then slices with `NaN`
   - `app2cli web open https://example.com --width abc` passes `NaN` viewport dimensions into the adapter layer
   - `app2cli session cleanup --purge-days banana` calculates `NaN * 24 * 60 * 60 * 1000`

   Impact: invalid values can turn into `NaN` viewports, `NaN` timeouts, empty query slices, or misleading session cleanup output instead of a clean CLI validation error.
   
   Recommendation: validate these options at the command boundary and fail with explicit user-facing messages.

## Overall Assessment

The repo has a solid amount of tested core logic, but there is still significant drift between the product contract and the actual CLI/runtime behavior. The biggest problems are not style issues: they are correctness and security gaps in session handling, Android orchestration, artifact integrity, and secret persistence. I would not consider the current CLI behavior production-ready until the high-severity findings are addressed.

## Suggested Follow-Up Order

If this feedback is used as a fix queue, the most sensible order is:

1. lock down the session-store path traversal
2. decide the real CLI session model and align implementation plus docs
3. fix `android run` so the command either truly works or is narrowed honestly
4. stop persisting and echoing cleartext typed secrets
5. fix snapshot artifact self-consistency
6. restore exact-ID query support for stable IDs
7. bring replay provenance parity to `type`
8. add option validation around numeric CLI inputs

## Engineering Action Plan

This section translates the review findings into implementation-sized work items with clear scope and acceptance criteria.

### Task 1: Lock down session-store path handling

Goal: make session file operations impossible to escape `.app2cli/sessions`.

Scope:
- `src/core/session-store.ts`
- `src/cli/commands/session.ts`
- tests for invalid session IDs and path traversal attempts

Changes expected:
- add session ID validation
- reject path separators, `.` and `..`, empty IDs, and null bytes
- enforce resolved-path-under-root checks before read/write/delete
- fail with a specific user-facing error instead of silently targeting a different path

Acceptance criteria:
- `session delete ../../package` does not target `package.json`
- `session get/touch/deactivate/delete` cannot operate outside the session directory
- there are regression tests covering traversal-like IDs
- normal session IDs such as `sess_abc123` still work unchanged

Suggested verification:
- unit tests for safe and unsafe IDs
- a direct path-resolution regression test proving the resolved path stays under the root

### Task 2: Resolve the real CLI session model

Goal: remove the contradiction between documented multi-command workflows and in-memory-only state.

Scope:
- `src/cli/state.ts`
- `src/cli/main.ts`
- runtime commands in `src/cli/commands/*.ts`
- `src/core/session-store.ts`
- `README.md`

Decision required:
- either implement persisted/resumable sessions across separate CLI invocations
- or explicitly redesign the CLI as a single-process/interactive model and remove the current cross-command claims

Changes expected if choosing persisted sessions:
- `web open` and `android open` persist enough state to resume
- `inspect/query/click/type/screenshot/export` can resolve an active or explicit session
- session list/cleanup/delete reflect the same session system the runtime commands use

Changes expected if choosing single-process semantics:
- remove or narrow docs that imply process-to-process continuity
- consider replacing current command flow with a shell/subcommand that stays alive
- align `session` commands with the actual supported runtime model

Acceptance criteria:
- the chosen UX is coherent in code, help text, and README
- the documented example flow is actually runnable as written
- session commands operate on the same concept of session that runtime commands use

Suggested verification:
- an end-to-end CLI test covering the documented flow
- README examples reviewed against actual command behavior

### Task 3: Make `android run` actually acquire, install, and launch

Goal: ensure `android run` matches its name, help text, and README contract.

Scope:
- `src/cli/commands/android.ts`
- `src/core/apk/pipeline.ts`
- APK providers in `src/core/apk/providers/`
- `src/adapters/android/appium-client.ts`
- `README.md`

Changes expected:
- support at least one real non-local acquisition path if `--app-id` and `--play-url` remain documented
- or narrow the command/API/docs so only supported inputs are accepted
- after local APK acquisition, determine the package/component to launch
- explicitly launch the installed app after install
- avoid using `"unknown"` as the long-term session target when better metadata is available

Acceptance criteria:
- `android run --apk <file>` installs and then launches the intended app
- `android run --app-id ...` either works through a real provider path or is rejected as unsupported at the CLI contract level
- `android run --play-url ...` either works through a real provider path or is rejected as unsupported at the CLI contract level
- session metadata and provenance identify the target app accurately

Suggested verification:
- unit tests for provider-chain selection
- integration-style tests for run-path orchestration with mocked adapter/provider boundaries
- README and command help updated to exactly match supported modes

### Task 4: Stop leaking typed secrets to stdout and artifacts

Goal: prevent cleartext user input from leaking through logs, replay files, and terminal output.

Scope:
- `src/cli/commands/action.ts`
- `src/core/replay/recorder.ts`
- artifact logging via `src/core/artifacts/writer.ts`
- redaction wiring via `src/core/redact.ts`
- docs describing replay/artifact behavior

Changes expected:
- remove raw typed text from default stdout output
- apply redaction to action logs and replay persistence
- define whether redaction is always-on, opt-in privacy mode, or configurable
- make the default safe for passwords, OTPs, bearer tokens, and other obvious sensitive input

Acceptance criteria:
- typing a password does not echo the password back to the terminal
- replay JSON/JSONL do not contain raw secrets by default
- action logs do not contain raw secrets by default
- tests cover password-like input, token-like input, and normal non-sensitive input

Suggested verification:
- replay tests asserting redacted output
- action-log tests asserting secret suppression/redaction
- manual smoke test with `type --query "field labeled password" "MySecret123!"`

### Task 5: Fix persisted snapshot self-consistency

Goal: ensure `source.json` is a faithful representation of the final saved snapshot.

Scope:
- `src/core/artifacts/writer.ts`
- callers in `src/cli/commands/web.ts`
- callers in `src/cli/commands/android.ts`
- callers in `src/cli/commands/inspect.ts`

Changes expected:
- write screenshot and raw source first
- fill `snapshot.artifacts` with the resolved paths
- then serialize the snapshot JSON
- avoid concurrent write ordering that captures stale artifact fields

Acceptance criteria:
- saved `source.json` contains the same artifact paths returned to the caller
- the persisted snapshot is self-contained and does not show null artifact fields after save
- a regression test reads the saved JSON back from disk and checks the artifact paths

Suggested verification:
- update `writer.test.ts` to assert final JSON content, not just returned paths

### Task 6: Restore exact-ID query support for stable IDs

Goal: make query-by-ID work with the node IDs the system now actually generates.

Scope:
- `src/core/query/selector-engine.ts`
- query tests
- docs/examples that mention node IDs

Changes expected:
- update exact-ID parsing to accept current stable ID format
- keep direct action resolution and query resolution consistent
- make sure legacy sequential IDs are handled intentionally if backward compatibility matters

Acceptance criteria:
- a node ID emitted by inspect output can be pasted into `app2cli query <id>` and resolve correctly
- tests cover both current stable IDs and any intentionally supported legacy ID format
- no mismatch remains between query-by-ID and action-by-ID behavior

Suggested verification:
- direct regression test for `n_<hash>_<index>` IDs

### Task 7: Bring replay provenance parity to `type`

Goal: make replay records for `type` as auditable as replay records for `click`.

Scope:
- `src/cli/commands/action.ts`
- `src/core/replay/recorder.ts`
- replay tests

Changes expected:
- preserve resolution metadata from `resolveNodeId(...)`
- pass `score` and `matchedBy` into `recordType(...)`
- keep replay output structure consistent across action types

Acceptance criteria:
- `type --query ...` replay entries include decision score and resolution strategy when available
- click and type replay entries have equivalent provenance fields for equivalent resolution paths
- tests cover both direct-ID and query-based type actions

Suggested verification:
- replay recorder or CLI command tests asserting `decisionScore` and `matchedBy` are populated for query-based typing

### Task 8: Validate numeric CLI options at the boundary

Goal: fail fast on invalid numeric options instead of letting `NaN` leak into lower layers.

Scope:
- `src/cli/commands/web.ts`
- `src/cli/commands/android.ts`
- `src/cli/commands/query.ts`
- `src/cli/commands/session.ts`

Changes expected:
- validate width, height, timeout, limit, and purge-days
- reject non-numeric, zero, negative, and otherwise invalid values where appropriate
- return clear, user-facing CLI errors

Acceptance criteria:
- invalid numeric input fails immediately with a clear message
- valid numeric input still behaves exactly as before
- there are tests for invalid values such as `abc`, `-1`, `0`, and empty-like cases where relevant

Suggested verification:
- command-level tests for option validation

## Definition Of Done For This Review Set

This feedback set should be considered fully addressed only when:

- the high-severity items are fixed in code, not just documented
- the README and CLI help match actual supported behavior
- regression tests exist for each fixed issue
- any deliberate non-support is made explicit at the command boundary instead of failing late or ambiguously
