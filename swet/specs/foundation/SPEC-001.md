# SPEC-001: Project Scaffolding

## Status
Approved

## Priority
P0

## Dependencies
- None

## Overview
Establish the monorepo structure, build tooling, and development environment for the SWET platform. This spec defines the foundational project layout that all subsequent specs build upon, including the backend (FastAPI), frontend (Next.js 15), database infrastructure (Docker Compose + PostgreSQL), and developer experience tooling (Makefiles, linting, formatting, pre-commit hooks).

## Requirements

### Functional
1. Monorepo with `backend/` (Python/FastAPI) and `app/` (Next.js/TypeScript) directories at the root alongside `specs/` for documentation
2. FastAPI application factory in `backend/src/main.py` with router registration and middleware setup
3. Next.js 15 App Router project in `app/` with TypeScript strict mode
4. Docker Compose configuration for PostgreSQL 18 (Alpine) with health checks and named volume
5. Root-level Makefile orchestrating `dev`, `db`, `test`, `lint`, `setup`, and `clean` targets across both services
6. Backend Makefile with targets: `setup`, `dev`, `test`, `test-unit`, `test-integration`, `test-cov`, `lint`, `format`, `migrate`, `migration`, `seed`, `clean`
7. Frontend Makefile with targets: `setup`, `dev`, `build`, `lint`, `test`, `test-cov`, `test-e2e`, `clean`
8. `pyproject.toml` with project metadata, dependencies, and tool configuration (ruff, mypy, pytest, coverage)
9. `package.json` with pnpm as package manager, all runtime and dev dependencies, and npm scripts
10. `.gitignore` covering Python, Node.js, IDE, and environment file patterns
11. `.env.example` files for both backend and frontend documenting required environment variables
12. Pre-commit configuration with ruff linting/formatting hooks for the backend

### Non-Functional
1. Backend dev server starts in under 3 seconds via `make dev`
2. Frontend dev server starts in under 5 seconds via `make dev`
3. PostgreSQL container reaches healthy state within 30 seconds
4. All Makefile targets produce clear success/failure output
5. `make setup` from a clean clone gets a developer to a running state in a single command

## Technical Design

### Project Structure
```
swet/
  backend/
    src/
      __init__.py
      main.py              # FastAPI app factory
      config.py            # Pydantic settings
      database.py          # Async SQLAlchemy engine/session
      dependencies.py      # Shared FastAPI dependencies
      errors.py            # Error hierarchy
      auth/                # Auth domain module
      onboarding/          # Onboarding domain module
      questions/           # Questions domain module
      assessments/         # Assessments domain module
      scoring/             # Scoring domain module
      cli/                 # CLI commands (seed data)
    tests/
    alembic/
    alembic.ini
    pyproject.toml
    Makefile
  app/
    src/
      app/                 # Next.js App Router pages
      components/          # React components (ui, layout, auth, assessment, results)
      lib/                 # Utilities, API client, hooks, stores, types
    tests/
    package.json
    tsconfig.json
    next.config.ts
    vitest.config.ts
    playwright.config.ts
    tailwind.config (via postcss + @tailwindcss/postcss v4)
    eslint.config.mjs
    Makefile
  specs/
  docker-compose.yml
  Makefile
  .gitignore
```

### Technology Stack
| Layer | Technology | Version |
|-------|-----------|---------|
| Frontend runtime | Node.js | LTS (22.x or 24.x) |
| Backend runtime | Python | 3.12+ |
| Backend framework | FastAPI | 0.115+ |
| ASGI server | Uvicorn | 0.32+ |
| ORM | SQLAlchemy (async) | 2.0.36+ |
| DB driver | asyncpg | 0.30+ |
| Migrations | Alembic | 1.14+ |
| Settings | pydantic-settings | 2.6+ |
| Frontend framework | Next.js (App Router) | 15.1+ |
| UI library | React | 19+ |
| Styling | Tailwind CSS v4 | 4.0+ |
| Component primitives | Radix UI + shadcn/ui | latest |
| State (server) | TanStack Query | 5.62+ |
| State (client) | Zustand | 5.0+ |
| Package manager (FE) | pnpm | 10.28+ |
| Linter (BE) | ruff | 0.8+ |
| Type checker (BE) | mypy (strict) | 1.13+ |
| Linter (FE) | ESLint | 9+ |
| Type checker (FE) | TypeScript (strict) | 5.7+ |
| Database | PostgreSQL (Alpine) | 18 |
| Containerization | Docker Compose | v2 |

### Docker Compose
- Single `postgres` service using `postgres:18-alpine`
- Port mapping: `5432:5432`
- Credentials: user `swet`, password `swet_local`, database `swet`
- Named volume `pgdata` for persistence
- Health check via `pg_isready -U swet` every 5s with 5 retries

### Backend Domain Module Convention
Each domain module (`auth/`, `onboarding/`, `questions/`, `assessments/`, `scoring/`) follows:
- `models.py` - SQLAlchemy ORM models
- `schemas.py` - Pydantic request/response schemas
- `service.py` - Business logic (never call ORM from router)
- `router.py` - FastAPI route definitions

## Implementation Notes
- The backend uses `src/` as a namespace package, not a top-level Python package install. Uvicorn runs via `src.main:app`.
- Tailwind CSS v4 uses the new PostCSS plugin (`@tailwindcss/postcss`) instead of the legacy `tailwindcss` CLI -- configuration is handled via `postcss.config.mjs`.
- The `pyproject.toml` `[tool.coverage.report]` `fail_under` is set to 85 from the start to enforce coverage discipline.
- mypy runs in strict mode from day one to prevent gradual typing debt.
- The root Makefile parallelizes `dev-be` and `dev-fe` with background processes and `wait`.

### Cross-Spec Guardrails
- API paths in backend specs must use versioned routes (`/api/v1/...`) and `{path_param}` syntax.
- Enum values shared across backend/frontend (question formats, statuses) must use a single canonical spelling (snake_case) across all specs.
- Lifecycle fields (e.g., `grading_status`) must define explicit allowed values and transitions in one primary spec, then be referenced elsewhere.
- Client retry/auto-save flows should document idempotency expectations and conflict behavior (`upsert`, dedupe key, and retry limits).

## Testing Strategy
- Unit tests for: Makefile target execution (smoke test that commands exist)
- Integration tests for: `docker compose up` brings PostgreSQL to a healthy state, backend `make dev` starts a responding server, frontend `make dev` starts a responding server
- E2E tests for: N/A at this stage

## Acceptance Criteria
- [ ] `git clone` + `make setup` succeeds on a clean machine with Python 3.12, Node.js LTS (22.x or 24.x), pnpm, and Docker installed
- [ ] `make db` starts PostgreSQL and passes health check
- [ ] `make dev` starts both backend (port 8000) and frontend (port 3000) dev servers
- [ ] Backend responds to `GET /` or `GET /docs` with 200
- [ ] Frontend renders the landing page at `http://localhost:3000`
- [ ] `make lint` runs ruff + mypy (backend) and ESLint + tsc (frontend) without errors
- [ ] `make test` runs pytest (backend) and Vitest (frontend) test suites
- [ ] `.gitignore` excludes `.venv/`, `node_modules/`, `.next/`, `__pycache__/`, `.env`
- [ ] `.env.example` files document all required environment variables for both services
- [ ] Pre-commit hooks run ruff checks on staged Python files
