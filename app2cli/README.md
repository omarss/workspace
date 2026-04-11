# app2cli

Convert live web applications and Android APKs into structured, machine-readable UI representations from the CLI.

app2cli produces a semantic UI model with visible text, element roles, accessibility metadata, bounds, interactable actions, hierarchy, and screenshots — not just plain OCR text.

## Installation

```bash
# from npm
npm install -g app2cli

# or run directly
npx app2cli --help

# or from source
git clone https://github.com/your-org/app2cli.git
cd app2cli
pnpm install
pnpm build
```

**Requirements:** Node.js >= 20

For web: Chromium (installed automatically via `npx playwright install chromium`)
For Android: adb, a connected device or emulator

## Quick Start

### Interactive Mode (multi-command workflows)

Multi-command workflows (open -> inspect -> query -> click) require the **interactive shell** to keep the session alive between commands:

```bash
$ app2cli shell
app2cli> web open https://example.com/login
app2cli> inspect
app2cli> query "button named sign in"
app2cli> click --query login
app2cli> exit
```

### Single Commands (one-shot)

Each standalone invocation is independent — use these for automation and scripting:

```bash
# one-shot snapshot to JSON
app2cli web snapshot https://example.com/login --format json
```

### Android

```bash
# interactive session
$ app2cli shell
app2cli> android boot
app2cli> android install ./app.apk
app2cli> android open com.example.app/.MainActivity
app2cli> inspect
app2cli> click --query submit

# or one-shot
app2cli android run --apk ./app.apk
```

## CLI Reference

### Platform Commands

| Command | Description |
|---------|-------------|
| `web open <url>` | Open a web page and establish a session |
| `web snapshot <url>` | Take a full snapshot (non-interactive) |
| `android boot` | Wait for an Android device to be ready |
| `android install <apk>` | Install an APK on the device |
| `android open <target>` | Launch an app and establish a session |
| `android run` | Acquire, install, launch APK in one step |

### Inspection

| Command | Description |
|---------|-------------|
| `inspect` | List all UI nodes on the current screen |
| `inspect --format json` | Full snapshot as JSON |
| `inspect --format patterns` | Detected UI patterns |
| `inspect --format semantic` | Semantic objects (forms, actions, nav) |
| `inspect --ocr` | Use OCR fallback for canvas/bitmap screens |

### Query

```bash
# by node ID
app2cli query n_14

# by role + name
app2cli query "button named sign in"

# by label
app2cli query "field labeled email"

# by text
app2cli query "clickable text contains continue"

# spatial/geometry
app2cli query "nearest button to n_5"
app2cli query "button below n_3"

# get just the ID (for piping)
app2cli query --id-only "field labeled email"
```

### Actions

```bash
# click by ID
app2cli click n_14

# click by query (with confidence enforcement)
app2cli click --query "button named sign in"
app2cli click --query submit --force    # override confidence threshold

# type
app2cli type n_9 "hello@example.com"
app2cli type --query "field labeled email" "hello@example.com"

# screenshot
app2cli screenshot
```

### Intent Shortcuts

Instead of writing selectors, use intent names for common actions:

| Intent | Description |
|--------|-------------|
| `login` | Click the sign-in / login button |
| `signup` | Click the sign-up / register button |
| `submit` | Click the submit / save / confirm button |
| `continue` | Click the continue / next button |
| `dismiss` | Close a dialog, banner, or popup |
| `back` | Navigate back |
| `search` | Focus the search input |

```bash
app2cli click --query login
app2cli click --query dismiss
app2cli intents list
app2cli intents resolve login
```

### Session Management

```bash
app2cli session list
app2cli session list --active
app2cli session cleanup
app2cli session cleanup --purge-days 7
app2cli session delete sess_abc123
```

### Export

```bash
app2cli export --format json
```

## Query Syntax

Resolution order (highest to lowest priority):

1. **Exact ID** — `n_14`
2. **Role + name** — `button named sign in`
3. **Exact text** — matches node text exactly
4. **Accessible name** — matches aria-label / content-desc
5. **Fuzzy text** — partial word matching
6. **Geometry** — `nearest button to n_5`, `input above n_3`

## Confidence Policy

Scores are enforced when using `--query` with action commands:

| Range | Level | Behavior |
|-------|-------|----------|
| >= 0.95 | Action safe | Click/type allowed |
| 0.85-0.94 | Query safe | Query returns results, actions blocked |
| < 0.85 | Ambiguous | Warning on query, actions blocked |

Use `--force` to override.

## Pattern Detection

17 built-in pattern detectors run automatically on every inspect:

**Auth:** login form, signup form, OTP screen
**Overlays:** modal dialog, bottom sheet, toast/snackbar
**Navigation:** top nav, bottom nav, tabs
**Content:** search surface, settings page, dashboard cards, list with actions, empty state, error state
**Commerce:** checkout form, payment picker

## Semantic Objects

Above raw nodes, app2cli extracts higher-level objects:

- **Forms** with labeled fields, validation state, primary/secondary actions
- **Navigation regions** with their items
- **Dialogs** with dismiss affordances
- **Error/success/warning messages**
- **Primary and secondary actions**

## APK Acquisition

The `android run` command supports multiple input formats:

```bash
app2cli android run --apk ./app.apk
app2cli android run --app-id com.example.app
app2cli android run --play-url "https://play.google.com/store/apps/details?id=com.example.app"
```

APKs are resolved through a pluggable provider chain:
1. **Local file** (default, always enabled)
2. **F-Droid** (opt-in, `--provider fdroid`)
3. **Custom providers** (plugin interface)

Every acquired APK is tracked with provenance: SHA-256, source, file size, timestamp.

## OCR Fallback

For canvas-rendered or bitmap-heavy screens with no structured UI data:

```bash
app2cli inspect --ocr
app2cli inspect --ocr --ocr-lang fra    # French
```

Uses Tesseract.js. OCR nodes have type `ocr_text` and include bounding boxes.

## Action Replay

Record and audit every action:

```bash
app2cli web open https://example.com --replay
app2cli click n_1       # recorded
app2cli type n_2 "hi"   # recorded
# replay saved on disconnect as replay.json + replay.jsonl
```

Each step records: timestamp, target, confidence score, match strategy, duration, error, screenshots.

## Docker

```bash
# CLI only
docker build -t app2cli .
docker run app2cli web snapshot https://example.com

# web worker (includes Chromium)
docker build -t app2cli-web -f infra/docker/web/Dockerfile .

# android worker (includes adb)
docker build -t app2cli-android -f infra/docker/android/Dockerfile .

# docker compose
docker compose run web-worker web snapshot https://example.com
```

## Architecture

```
src/
  cli/           CLI entry point and commands
  core/
    schema/      Zod-validated canonical JSON schema
    query/       Selector engine with 6-tier resolution
    patterns/    17 rule-based UI pattern detectors
    semantic/    Form/action/nav/dialog extraction
    intents/     Intent shortcuts (login, dismiss, etc.)
    ocr/         Tesseract.js OCR fallback
    apk/         APK acquisition and provenance
    artifacts/   Per-session artifact persistence
    replay/      Action replay recorder
    redact.ts    Log redaction and privacy
    retry.ts     Retry with exponential backoff
    stable-id.ts Hash-based stable node IDs
  adapters/
    web/         Playwright + Chromium adapter
    android/     adb + UiAutomator adapter
```

Both platforms normalize into one canonical JSON schema so downstream tools don't care about the source platform.

## Development

```bash
pnpm install
make check      # lint + typecheck + test
make build      # compile
make dev        # run CLI in dev mode
make lint       # lint only
make test       # test only
```

## License

MIT
