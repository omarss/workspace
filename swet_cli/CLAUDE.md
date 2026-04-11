# SWET

Software engineering assessment tool with CLI, REST API, web frontend, Telegram bot, Slack bot, and WhatsApp bot. Generates adaptive questions across 29 competencies, 12 engineering roles, and 5 career levels using the Software Engineering Competency Matrix.

## Required Reading

- `CONVENTIONS.md` is the engineering standard for this repository.
- Follow `CONVENTIONS.md` for architecture, code organization, typing, security, scalability, performance, testing, dependency hygiene, CVE handling, and example implementation patterns.
- Use this `CLAUDE.md` for repo-specific orientation and system layout.
- If existing code conflicts with `CONVENTIONS.md`, prefer `CONVENTIONS.md` unless there is an explicit documented exception.

## Quick Reference

```bash
# CLI
make setup        # create venv and install deps (CLI + dev)
swet setup        # configure roles, languages, frameworks → auto-assesses level
swet              # get a question
swet test         # re-run level assessment (Bayesian adaptive testing)
swet session -n 5 # multi-question session
swet stats        # view performance by competency
swet competencies # list all 29 competencies with levels
swet config edit  # interactively edit preferences

# API
make run-api      # start FastAPI server on port 8000 (Swagger at /docs)
make test         # run all tests (CLI + API + Telegram + Slack + WhatsApp)
make test-api     # run API tests only
make lint         # ruff check + format check
make format       # auto-fix lint + format

# Telegram Bot
make setup-bot    # create venv and install deps (Telegram + dev)
make run-bot      # start Telegram bot (requires SWET_TELEGRAM_BOT_TOKEN)
make test-bot     # run Telegram bot tests only

# Slack Bot
make setup-slack  # create venv and install deps (Slack + dev)
make run-slack    # start Slack bot (requires SWET_SLACK_BOT_TOKEN + SWET_SLACK_APP_TOKEN)
make test-slack   # run Slack bot tests only

# WhatsApp Bot
make setup-whatsapp  # create venv and install deps (WhatsApp + dev)
make run-whatsapp    # start WhatsApp bot (requires Twilio credentials)
make test-whatsapp   # run WhatsApp bot tests only

# Web Frontend
make setup-web       # install pnpm dependencies
make dev-web         # start Vite dev server (HMR)
make build-web       # production build to web/build/
make deploy-web      # build + reload nginx
```

## Architecture

```
src/
  swet_cli/                    # CLI package (standalone, no API dependency)
    main.py                    # typer entry point, commands, question flow, assessment
    adaptive.py                # shared adaptive algorithm: Protocol-based, used by all entrypoints
    adaptive_db.py             # DB adapters: UserScopedDB (bots/API), SingletonDB (CLI)
    assessment.py              # Bayesian adaptive level assessment (CAT/IRT)
    data.py                    # loads competency_matrix.json, role weights, tech taxonomy
    generator.py               # LLM question generation, prompt building, response parsing
    db.py                      # SQLite schema, CRUD, performance queries
    prompts.py                 # LLM prompt templates for generation and grading
    grader.py                  # MCQ auto-grading + LLM-based open-ended grading
    llm.py                     # Anthropic API / OpenAI proxy client
    display.py                 # Rich terminal rendering
    models.py                  # Pydantic models (GeneratedQuestion, GradeResult)
    config.py                  # env var loading, Config singleton
    competency_matrix.json     # the full matrix (source of truth)

  swet_api/                    # REST API package (separate DB, user-scoped)
    app.py                     # FastAPI app, CORS, lifespan
    config.py                  # API config (JWT, OTP, DB path)
    db.py                      # user-scoped schema (all tables have user_id)
    schemas.py                 # shared Pydantic request/response models
    auth/
      router.py                # /auth/register, /auth/otp/send, /auth/otp/verify, /auth/refresh
      jwt.py                   # JWT creation/validation (HS256, PyJWT)
      otp.py                   # OTP generation, hashing (SHA-256)
      providers.py             # OTP delivery: ConsoleOTPProvider, Twilio, SendGrid
      dependencies.py          # FastAPI Depends() for get_current_user
      schemas.py               # auth request/response models
    engine.py                  # thin adapter: binds user_id to shared adaptive.py via UserScopedDB
    services/
      attempt_service.py       # grading, adaptive updates, review enqueueing
      question_service.py      # adaptive generation, reusable by sessions/assessments
    routers/
      preferences.py           # GET/PUT /preferences
      questions.py             # POST /questions/generate, GET /questions/next, GET /questions/{id}
      attempts.py              # POST /attempts (grade + save + adaptive update), GET /attempts/history
      stats.py                 # GET /stats, /stats/streak, /stats/competencies, /stats/calendar, /stats/format-performance, /stats/weak-areas
      bookmarks.py             # GET/POST/DELETE /bookmarks (auto-enqueues review)
      assessments.py           # POST /assessments, GET /assessments/current, POST /{id}/answer, POST /{id}/finalize, GET /{id}, DELETE /{id}
      sessions.py              # POST /sessions, GET /sessions/current, POST /{id}/answer, POST /{id}/end, GET /{id}, GET /sessions/history
      reviews.py               # GET /reviews, GET /reviews/count, POST /{id}/complete, POST /{id}/snooze, DELETE /{id}
      dashboard.py             # GET /dashboard (aggregated Today page data)

  swet_telegram/                 # Telegram bot package (separate DB, user-scoped by chat_id)
    bot.py                     # ApplicationBuilder entry point, handler wiring
    config.py                  # env var loading (SWET_TELEGRAM_BOT_TOKEN, DB path)
    db.py                      # user-scoped SQLite (chat_id as user_id)
    engine.py                  # thin adapter: binds user_id to shared adaptive.py
    formatters.py              # Telegram HTML rendering, message splitting
    keyboards.py               # InlineKeyboardMarkup builders
    handlers/
      setup.py                 # /start, /config — ConversationHandler for onboarding
      question.py              # /q — get question, answer, grade (MCQ + open-ended)
      session.py               # /session — multi-question practice session
      assessment.py            # /test — Bayesian adaptive level assessment
      stats.py                 # /stats, /history, /competencies, /bookmarks, /help

  swet_slack/                    # Slack bot package (separate DB, user-scoped by Slack user ID)
    bot.py                     # slack-bolt App + SocketModeHandler entry point
    config.py                  # env var loading (SWET_SLACK_BOT_TOKEN, SWET_SLACK_APP_TOKEN, DB path)
    db.py                      # user-scoped SQLite (Slack user ID as user_id)
    engine.py                  # thin adapter: binds user_id to shared adaptive.py
    formatters.py              # Slack mrkdwn rendering, message splitting (3000 char limit)
    blocks.py                  # Block Kit JSON builders (buttons, actions, sections)
    handlers/
      setup.py                 # /swet-setup, /swet-config — DB state-tracked onboarding
      question.py              # /swet-q — get question, answer via buttons or text
      session.py               # /swet-session — multi-question practice session
      assessment.py            # /swet-test — Bayesian adaptive level assessment
      stats.py                 # /swet-stats, /swet-history, /swet-competencies, /swet-help

  swet_whatsapp/                 # WhatsApp bot package (separate DB, user-scoped by phone number)
    bot.py                     # Flask webhook app + Twilio integration
    config.py                  # env var loading (Twilio credentials, DB path, webhook host/port)
    db.py                      # user-scoped SQLite (phone number as user_id)
    engine.py                  # thin adapter: binds user_id to shared adaptive.py
    formatters.py              # WhatsApp markdown rendering, MCQ as text (A/B/C/D)
    handlers/
      setup.py                 # /start — text-based step-by-step onboarding
      question.py              # /q — get question, answer via text reply
      session.py               # /session — multi-question practice session
      assessment.py            # /test — Bayesian adaptive level assessment (serialized state)
      stats.py                 # /stats, /history, /competencies, /bookmarks, /help

web/                             # SPA frontend (SvelteKit + Tailwind, calls REST API)
  package.json                 # pnpm, SvelteKit, Tailwind v4, ky, marked, shiki
  svelte.config.js             # static adapter, SPA fallback to index.html
  vite.config.ts               # Vite + Tailwind + SvelteKit plugins
  src/
    app.html                   # Shell HTML (dark mode, Google Fonts)
    app.css                    # Tailwind theme tokens, dot-grid, markdown styles
    lib/
      api/                     # ky-based API client layer
        client.ts              # ky instance with JWT auth + auto token refresh
        types.ts               # TypeScript interfaces mirroring API schemas
        auth.ts                # register(), sendOtp(), verifyOtp()
        preferences.ts         # getPreferences(), updatePreferences()
        questions.ts           # generateQuestions(), getNextQuestion(), getQuestion()
        attempts.ts            # submitAnswer(), getHistory()
        stats.ts               # getStats(), getStreak(), getCompetencyLevels(), getCalendar(), getFormatPerf(), getWeakAreas()
        bookmarks.ts           # listBookmarks(), addBookmark(), removeBookmark()
        assessment.ts          # startAssessment(), submitAnswer(), getResults(), cancel()
        sessions.ts            # startSession(), submitAnswer(), endSession(), getHistory()
        review.ts              # getReviewQueue(), completeReview(), snoozeReview(), dismissReview()
        today.ts               # getDashboard()
      stores/
        auth.svelte.ts         # Reactive auth store (localStorage-persisted JWT)
        app.svelte.ts          # Global loading state + toast notifications
      data/
        matrix.json            # Extracted from competency_matrix.json at build time
        index.ts               # Roles, competencies, taxonomy, filtering logic (mirrors data.py)
      components/
        QuestionCard.svelte    # Format dispatcher: routes to format-specific renderers
        GradeReveal.svelte     # Score reveal + criteria + follow-up actions + bookmark sync
        formats/
          McqQuestion.svelte         # MCQ with keyboard shortcuts (1-4/A-D)
          CodeReviewQuestion.svelte  # Line-annotated code review with clickable gutter
          DebuggingQuestion.svelte   # Bug location + fix + explanation fields
          DesignPromptQuestion.svelte # Structured sections (architecture, data model, trade-offs, scalability)
          ShortAnswerQuestion.svelte # Textarea with character count guidance
      assessment.ts            # BayesianLevelEstimator ported from assessment.py
      utils/
        markdown.ts            # marked + DOMPurify renderer
        format.ts              # Slug formatting, time/score helpers
    routes/
      +layout.svelte           # Root layout (CSS import, toast overlay)
      +page.svelte             # Redirect: auth → /today, unauth → /login
      login/+page.svelte       # OTP auth (register/login tabs, 6-digit code input)
      (app)/                   # Authenticated group (nav bar, auth guard)
        +layout.svelte         # App shell: Today | Train | Review | Progress | Settings
        today/+page.svelte     # Daily hub: streak, focus skill, workout, review queue
        train/+page.svelte     # Session/workout mode: workout, practice, challenge
        review/+page.svelte    # Spaced repetition review queue (from bookmarks + misses)
        progress/+page.svelte  # Mastery view: competency levels, streak, weak areas
        assess/+page.svelte    # Bayesian calibration assessment flow
        settings/+page.svelte  # Profile wizard (roles, languages, frameworks, formats, length)
  build/                       # Production output (served by nginx)
```

## Key Design Decisions

- **Opus 4.6 only** for question generation. Sonnet for grading.
- **Per-competency adaptive difficulty** using ELO-like ratings (not global difficulty).
- **No manual difficulty selection** — level is determined by Bayesian adaptive testing (IRT model) during setup and updated via ELO after every answer.
- **Smart DB caching**: questions generated in batches of 10, served from SQLite. LLM only called when DB lacks suitable questions or staleness/topic-overlap detected.
- **Shared adaptive engine** — `swet_cli/adaptive.py` is the single source of truth for competency/format selection and ELO updates. All entrypoints (CLI, API, Telegram, Slack, WhatsApp) use it via `AdaptiveDB` protocol adapters in `adaptive_db.py`. Each engine.py is a ~60-line thin adapter.
- **Service layer (API)** — `services/attempt_service.py` and `services/question_service.py` handle grading, adaptive updates, and generation. Routers are thin HTTP adapters.
- **CLI, API, and all bots are independent** — separate packages, separate databases. All share `swet_cli.adaptive`, `swet_cli.generator`, `swet_cli.grader`, and `swet_cli.data`.
- **User-scoped API and bots** — every table has a `user_id` column. Users cannot see each other's data.
- **OTP-only auth (API)** — no passwords. Register with email or mobile, verify via OTP, get JWT.
- **Chat ID auth (Telegram)** — no passwords or OTP. Users identified by Telegram chat_id, auto-created on first interaction.
- **Slack user ID auth (Slack)** — users identified by Slack user ID (U0ABC123), auto-created on first interaction.
- **Phone number auth (WhatsApp)** — users identified by WhatsApp phone number, auto-created on first message.
- **Web frontend is a pure static SPA** — SvelteKit with static adapter, calls the REST API directly. No Python backend for the web. Served by nginx from `web/build/`.
- **Same-origin deployment** — nginx serves both the SPA (static files) and proxies API routes to uvicorn. No CORS issues.

## Adaptive Algorithm (adaptive.py)

### Competency Selection (5 signals blended)
1. Role emphasis weights from the matrix (very_high=0.30, high=0.20, medium=0.10, low=0.05)
2. Performance gap: weaker competencies weighted higher (ZPD targeting)
3. Spaced repetition: exponential decay (14-day half-life)
4. Coverage balancing: under-practiced competencies get bonus
5. Diversity penalty: recently attempted competencies downweighted

### Difficulty Adaptation (per-competency ELO)
- Decision hierarchy: explicit override > ELO level > rolling avg > base difficulty
- ELO rating range 200-2200, mapped to levels 1-5 via thresholds
- 3 consecutive high scores (>0.80) triggers promotion
- 3 consecutive low scores (<0.35) triggers demotion
- Mid-range scores (0.35-0.80) reset consecutive counters

### Format Selection (adaptive + user preferences)
- Base weights shift by level (juniors get more MCQ, seniors get more design)
- User-preferred formats get 3x boost, non-preferred get 0.1x
- Formats where the user scores poorly get boosted
- Untried formats get a slight bonus

### Question Length Preference
- User selects concise/standard/detailed during setup or via `swet config set --length`
- Injected into the LLM generation prompt to control verbosity
- Concise: brief questions, short code (<30 lines), minimal preamble
- Standard: default behavior (no extra prompt instruction)
- Detailed: rich context, longer code (40-80 lines), real-world scenarios

### Level Assessment (assessment.py)
- Computerized Adaptive Testing using Item Response Theory (IRT 1PL model)
- Bayesian posterior over levels 1-5, bell-shaped prior centered on L3
- 3 MCQ questions per competency, difficulty adapts based on answers
- Top 6 competencies selected from role emphasis (very_high + high)
- Results stored as ELO midpoints for seamless continuation

### Smart Generation Decision (should_generate_new)
- Serves from DB queue when matching questions exist
- Regenerates on: level mismatch, >60% topic overlap with recent questions, no matching queue

## Setup Filtering (data.py)

Languages and frameworks shown during setup are filtered in two layers:
1. **By role**: each role maps to specific taxonomy domains (e.g., backend → backend_frameworks + databases + ORMs)
2. **By language**: items in `_TECH_TO_LANGUAGES` are only shown if the user selected that language. Items not in the mapping are language-agnostic (always shown).

## REST API

### Auth Flow (OTP-only, no passwords)
```
POST /auth/register       {email or mobile}  →  201
POST /auth/otp/send       {email or mobile}  →  200 (OTP delivered via configured provider)
POST /auth/otp/verify     {email/mobile, code}  →  {access_token, refresh_token}
POST /auth/refresh        {refresh_token}  →  new token pair (old revoked)
```

### Protected Endpoints (Bearer JWT)
All return 401 for invalid/expired tokens. User data is scoped by JWT subject.
38 total endpoints: auth (4), preferences (2), questions (3), attempts (2), stats (6), bookmarks (3), assessments (6), sessions (6), reviews (5), dashboard (1).

### API Database
Separate SQLite at `~/.local/share/swet_api/swet_api.db` (configurable via `SWET_API_DB_PATH`).
Same schema as CLI but every table has `user_id` column. Additional tables:
- Auth: `users`, `otp_codes`, `refresh_tokens`
- Training: `assessments` (Bayesian posteriors serialized to JSON), `sessions`, `session_results`
- Review: `review_queue` (SM-2 spaced repetition with ease_factor and interval)
- `attempts` table has additional `confidence` column (1-5 nullable)

### Environment Variables
```
SWET_API_JWT_SECRET        # required for production (auto-generated in dev)
SWET_API_DB_PATH           # override default DB location
SWET_API_OTP_PROVIDER      # "console" (default), "twilio", "sendgrid"
ANTHROPIC_API_KEY          # required for question generation and grading
```

## Telegram Bot

### Commands
```
/start          — Set up profile (roles, languages, frameworks, formats, length)
/q              — Get an adaptive question (MCQ via buttons, open-ended via text)
/session [N]    — Multi-question practice session (default: select 3/5/10)
/test           — Run Bayesian adaptive level assessment
/stats          — View performance stats by competency
/history [N]    — View recent attempt history
/competencies   — List all 29 competencies with levels
/bookmarks      — View bookmarked questions
/preferences    — View current preferences
/config         — Edit preferences interactively
/help           — Show command list
/cancel         — Cancel current operation
```

### Telegram Bot Database
Separate SQLite at `~/.local/share/swet_telegram/swet_telegram.db` (configurable via `SWET_TELEGRAM_DB_PATH`).

### Telegram Bot Environment Variables
```
SWET_TELEGRAM_BOT_TOKEN    # required (get from @BotFather)
SWET_TELEGRAM_DB_PATH      # override default DB location
ANTHROPIC_API_KEY          # required for question generation and grading
```

### Telegram-Specific Design
- **engine.py** is a thin adapter binding user_id to the shared `swet_cli.adaptive` module via `UserScopedDB`. All algorithm logic lives in `adaptive.py`.
- **Pure functions** (`generate_questions`, `grade_mcq`, `grade_open_ended`, `BayesianLevelEstimator`) are imported directly from `swet_cli`.
- **Async wrapping**: sync LLM calls wrapped in `asyncio.to_thread()` to avoid blocking the bot's event loop.
- **Message splitting**: Telegram's 4096-char limit handled by `formatters._split_message()`.
- **ConversationHandler** used for multi-step flows (setup, assessment, session, open-ended questions).
- **Inline keyboards** for MCQ answers, setup toggles, and post-answer actions.

## Slack Bot

### Commands
```
/swet-setup     — Set up profile (roles, languages, frameworks, formats, length)
/swet-config    — Edit preferences interactively
/swet-q         — Get an adaptive question (MCQ via buttons, open-ended via text)
/swet-session   — Multi-question practice session
/swet-test      — Run Bayesian adaptive level assessment
/swet-stats     — View performance stats by competency
/swet-history   — View recent attempt history
/swet-competencies — List all 29 competencies with levels
/swet-bookmarks — View bookmarked questions
/swet-preferences — View current preferences
/swet-help      — Show command list
```

### Slack Bot Database
Separate SQLite at `~/.local/share/swet_slack/swet_slack.db` (configurable via `SWET_SLACK_DB_PATH`).

### Slack Bot Environment Variables
```
SWET_SLACK_BOT_TOKEN       # required (xoxb- token from Slack app)
SWET_SLACK_APP_TOKEN       # required (xapp- token for Socket Mode)
SWET_SLACK_DB_PATH         # override default DB location
ANTHROPIC_API_KEY          # required for question generation and grading
```

### Slack-Specific Design
- **slack-bolt** framework with Socket Mode (no public URL needed).
- **Block Kit** for rich interactive messages (buttons, sections, actions).
- **Conversation state** tracked in DB `state` table (no built-in ConversationHandler like Telegram).
- **Assessment state** kept in-memory (`_active_assessments` dict) for short-lived flows.
- **3-second ack rule**: all slash commands ack() immediately, then respond asynchronously for LLM calls.
- **Slack mrkdwn** formatting (`*bold*`, `` `code` ``, ` ```blocks``` `). 3000-char block text limit.
- **Message listener** (`app.message()`) for open-ended text answers, routed via DB state.

## WhatsApp Bot

### Commands
```
/start          — Set up profile (text-based step-by-step onboarding)
/q              — Get an adaptive question (MCQ via A/B/C/D text reply)
/session [N]    — Multi-question practice session
/test           — Run Bayesian adaptive level assessment
/stats          — View performance stats
/history [N]    — View recent attempt history
/competencies   — List all 29 competencies with levels
/bookmarks      — View bookmarked questions
/preferences    — View current preferences
/config         — Edit preferences
/help           — Show command list
/cancel         — Cancel current operation
```

### WhatsApp Bot Database
Separate SQLite at `~/.local/share/swet_whatsapp/swet_whatsapp.db` (configurable via `SWET_WHATSAPP_DB_PATH`).

### WhatsApp Bot Environment Variables
```
SWET_WHATSAPP_ACCOUNT_SID    # required (Twilio account SID)
SWET_WHATSAPP_AUTH_TOKEN     # required (Twilio auth token)
SWET_WHATSAPP_PHONE_NUMBER   # required (whatsapp-enabled Twilio number, e.g., whatsapp:+1234567890)
SWET_WHATSAPP_DB_PATH        # override default DB location
SWET_WHATSAPP_HOST           # webhook host (default: 0.0.0.0)
SWET_WHATSAPP_PORT           # webhook port (default: 5000)
ANTHROPIC_API_KEY            # required for question generation and grading
```

### WhatsApp-Specific Design
- **Flask webhook** app with single `/webhook` POST endpoint for Twilio.
- **Fully stateless**: ALL conversation state serialized to SQLite between webhook calls (no in-memory state).
- **Twilio signature validation** for webhook security.
- **MCQ via text reply**: WhatsApp limits buttons to 3, so MCQ options (A/B/C/D) are rendered as text. Users reply with a letter.
- **BayesianLevelEstimator** posterior (`dict[int, float]`) serialized to JSON for assessment state persistence.
- **Text-based setup**: numbered options with comma-separated selection (no inline buttons for multi-select).
- **WhatsApp markdown** formatting (`*bold*`, `_italic_`, ` ```code``` `). 4096-char message limit.
- **24-hour session window**: all interactions are user-initiated, so this is naturally satisfied.

## Web Frontend

### Tech Stack
- **SvelteKit** with static adapter (compiles to static HTML/JS/CSS)
- **Tailwind CSS v4** with custom dark theme tokens
- **ky** for HTTP (JWT interceptor with auto token refresh)
- **marked + DOMPurify** for rendering markdown question bodies
- **Svelte 5 runes** for reactive state ($state, $derived)

### Design
- Dark-first theme: near-black `#0a0a0f` background, cyan `#06b6d4` accent
- JetBrains Mono for code, Inter for prose (Google Fonts)
- Difficulty color-coded: L1 green, L2 blue, L3 purple, L4 orange, L5 red
- MCQ keyboard shortcuts (1-4 / A-D), animated score reveals
- Progressive disclosure: main screen shows one question at a time

### Pages
- `/login` — OTP auth flow (register/sign-in tabs, 6-digit auto-advancing input)
- `/today` — Daily hub: streak, stats, quick practice, workout, focus skill, review count, assessment prompt
- `/train` — Session/workout mode: select count (5/10/custom), progress bar, grade after each Q, summary
- `/review` — Spaced repetition queue: filter tabs (all/missed/saved), snooze/dismiss/review actions
- `/progress` — Mastery view: streak calendar, weak areas, competency levels, format performance, inline history
- `/assess` — Bayesian calibration: 18 adaptive MCQ → mastery map with confidence bars and posteriors
- `/settings` — Multi-step profile wizard (roles → languages → frameworks → formats → length), redirects to /assess on first setup

### Static Data
`web/src/lib/data/matrix.json` is extracted from `competency_matrix.json`. The filtering logic in `web/src/lib/data/index.ts` mirrors `swet_cli/data.py` (role-based language/framework filtering, `_TECH_TO_LANGUAGES` mapping).

### Assessment Algorithm
`web/src/lib/assessment.ts` ports `BayesianLevelEstimator` from `swet_cli/assessment.py` to TypeScript. Constants (`IRT_DISCRIMINATION`, `LEVEL_PRIOR`, `LEVEL_ELO_MIDPOINTS`) match exactly.

### Deployment
- **Domain**: `https://swet.omarss.net` (Let's Encrypt SSL, auto-renewing)
- **nginx**: serves SPA static files + proxies API routes (`/auth/`, `/preferences`, `/questions`, `/attempts`, `/stats`, `/bookmarks`, `/assessments`, `/sessions`, `/reviews`, `/dashboard`, `/health`, `/docs`) to uvicorn on port 8000
- **uvicorn**: 4 workers via systemd service (`swet-api.service`)
- **WSL port forwarding**: Windows scheduled task (`WSL-PortProxy`) auto-updates `netsh portproxy` rules on boot with WSL's dynamic IP

## CLI Database

SQLite at `~/.local/share/swet_cli/swet.db`. Key tables:
- `preferences` — singleton row: roles, languages, frameworks, preferred_formats, question_length
- `questions` — generated questions with metadata
- `attempts` — answer submissions with scores
- `competency_levels` — per-competency ELO rating, consecutive scores, total attempts
- `format_performance` — running average score per competency+format
- `bookmarks`, `difficulty_overrides`, `state` (streaks)

## Testing

- CLI tests use temp SQLite DB (set via `SWET_CLI_DB_PATH` before imports)
- API tests use temp SQLite DB (set via `SWET_API_DB_PATH` before imports)
- Telegram tests use temp SQLite DB (set via `SWET_TELEGRAM_DB_PATH` before imports)
- Slack tests use temp SQLite DB (set via `SWET_SLACK_DB_PATH` before imports)
- WhatsApp tests use temp SQLite DB (set via `SWET_WHATSAPP_DB_PATH` before imports)
- Each test gets a fresh DB via autouse `_cleanup` fixture
- No LLM calls in tests — algorithm logic, DB operations, parsing, and API e2e flows
- API e2e tests insert questions directly (skip LLM) and exercise complete user journeys
- 446 total tests across 17 test files

## Common Patterns

- `save_question()` / `save_user_question()` handle `json.dumps` for dict fields. Pass dicts directly, not pre-serialized JSON strings.
- `get_preferences()` returns `{roles, languages, frameworks, difficulty, preferred_formats, question_length}` or `None`.
- Competency slugs: `programming_fundamentals`, `ai_engineering_and_llm_systems`
- Role IDs: `backend_engineer`, `site_reliability_engineer`
- The `role` column in the preferences table stores a JSON array despite its singular name (backward compat).
