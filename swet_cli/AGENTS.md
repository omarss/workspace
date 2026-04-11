# Agent Instructions

Start here when operating in this repository.

## Reading Order

1. `CONVENTIONS.md`
2. `CLAUDE.md`

## What Each File Controls

- `CONVENTIONS.md` is the engineering standard for this repo. It defines required practices for architecture, code organization, typing, security, scalability, performance, testing, dependency hygiene, deprecated APIs, and CVE handling. It includes example implementation patterns that should be treated as the default way to structure new work.
- `CLAUDE.md` provides repository-specific context: package layout, commands, runtime surfaces, current architectural shape, database schemas, and deployment configuration.

## Priority Rule

- If existing code conflicts with `CONVENTIONS.md`, prefer `CONVENTIONS.md` unless there is a documented exception or an explicit higher-priority instruction in the active task context.

## Key Architecture Rules

### Shared Domain Layer
- `swet_cli/adaptive.py` is the single source of truth for the adaptive algorithm (competency selection, format selection, ELO, difficulty adaptation). Do not duplicate this logic.
- `swet_cli/adaptive_db.py` provides `AdaptiveDB` Protocol + `UserScopedDB` / `SingletonDB` adapters. All entrypoints bind their DB through these adapters.
- Each bot and API `engine.py` is a thin adapter (~60 lines). It binds `user_id` into a `UserScopedDB` and delegates to `adaptive.py`. Never add algorithm logic to engine files.
- Pure functions (`generate_questions`, `grade_mcq`, `grade_open_ended`, `BayesianLevelEstimator`) live in `swet_cli` and are imported directly by all entrypoints.

### API Service Layer
- `swet_api/services/attempt_service.py` handles grading, adaptive updates, and review enqueueing. Routers call this instead of doing grading inline.
- `swet_api/services/question_service.py` handles adaptive generation. Reused by sessions and assessments routers.
- Routers must stay thin: validate input, call service, return response. No SQL, no grading logic, no adaptive algorithm calls in routers.

### Database Access
- Each package (CLI, API, Telegram, Slack, WhatsApp) has its own `db.py` with its own SQLite database.
- API DB functions use `user_id` as first parameter. CLI DB functions have no `user_id` (singleton).
- Bot/API DB functions follow the naming pattern `get_user_*`, `update_user_*`, `save_user_*`.
- Always close connections. Use `try/finally` for functions that open connections and run multiple queries.

### Web Frontend
- Pages: `/today`, `/train`, `/review`, `/progress`, `/assess`, `/settings`
- `QuestionCard.svelte` dispatches to format-specific renderers in `components/formats/`
- API clients in `lib/api/` — one module per domain (assessment, sessions, review, today, stats, etc.)
- Timer intervals must be cleared in `onDestroy` to prevent memory leaks
- All markdown rendered through `renderMarkdown()` (marked + DOMPurify)

### Testing
- 446 tests across 17 files. All must pass before merge.
- API e2e tests insert questions directly (skip LLM) via `save_user_question()`
- Each test gets a fresh temp DB via autouse `_cleanup` fixture
- Assessment and session endpoints need additional E2E test coverage

### What Not To Do
- Do not copy adaptive algorithm logic into a new engine file. Use `adaptive.py` + `UserScopedDB`.
- Do not put grading or adaptive update logic in routers. Use the service layer.
- Do not add new Flask services. FastAPI is the standard.
- Do not use `onMount` for route-level data when `+page.ts` `load()` is more appropriate (known debt, migrate when touching those files).
- Do not store long-lived refresh tokens in browser-readable storage without documented risk acceptance.
