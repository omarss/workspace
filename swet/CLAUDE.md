# SWET - Software Engineering Test

Professional-grade assessment platform that identifies and helps elevate software engineering competencies across 12 core areas.

## Tech Stack

- **Backend**: Python 3.12.x, FastAPI, SQLAlchemy (async), Alembic, PostgreSQL
- **Frontend**: Next.js 15 (App Router), TypeScript, Tailwind CSS v4, shadcn/ui
- **Runtimes**: Node.js LTS (`.nvmrc`), Python 3.12 (`.python-version`)
- **Auth**: NextAuth.js v5 (GitHub provider) + backend JWT validation via `fastapi-nextauth-jwt`
- **AI**: Claude (Anthropic SDK) - Sonnet for question generation, Opus for grading
- **Testing**: pytest + pytest-asyncio (backend), Vitest + Playwright (frontend)
- **Package Managers**: pip + venv (backend), pnpm (frontend)

## Project Structure

```
swet/
  backend/         # FastAPI backend (Python 3.12)
    src/           # Source code organized by domain
      auth/        # Authentication (models, router, schemas, service)
      onboarding/  # User profile setup
      questions/   # Question models, generation, caching
      assessments/ # Assessment engine, answers, progress
      scoring/     # Grading, results, competency scores
      cli/         # CLI commands (seed data)
    tests/         # pytest test suite
    alembic/       # Database migrations
  app/             # Next.js 15 frontend (TypeScript)
    src/app/       # App Router pages
    src/components/ # React components (ui, layout, auth, assessment, results)
    src/lib/       # Utilities, API client, hooks, stores, types
    tests/         # Vitest + Playwright tests
  specs/           # Specification documents
```

## Development Commands

### Root Level
- `make dev` - Start all services (PostgreSQL + backend + frontend)
- `make db` - Start PostgreSQL via Docker Compose
- `make test` - Run all tests (backend + frontend)
- `make lint` - Run all linters
- `make setup` - First-time setup (DB + backend venv + frontend packages)

### Backend (`cd backend/`)
- `make setup` - Create venv and install dependencies
- `make dev` - Run FastAPI dev server (port 8000)
- `make test` - Run all backend tests
- `make test-cov` - Run tests with coverage report
- `make lint` - Run ruff + mypy
- `make format` - Auto-format code
- `make migrate` - Run Alembic migrations
- `make seed` - Seed competencies and role weights

### Frontend (`cd app/`)
- `make setup` - Install pnpm dependencies
- `make dev` - Run Next.js dev server (port 3000)
- `make test` - Run Vitest tests
- `make test-e2e` - Run Playwright E2E tests
- `make lint` - Run ESLint + TypeScript check
- `make build` - Production build

## Architecture Rules

- Follow spec-driven development: write spec -> write tests -> implement -> refactor
- Every domain module has: `models.py`, `schemas.py`, `service.py`, `router.py`
- Use dependency injection via FastAPI `Depends()`
- All DB operations go through service layer (never call ORM from router)
- Frontend uses TanStack Query for server state, Zustand for client state
- Auth: NextAuth handles OAuth, backend validates JWT on every request
- Question pools are cached by config_hash (SHA-256 of role + technologies)
- All API endpoints return standardized error format via `AppError` hierarchy

## Database

- PostgreSQL 18 via Docker Compose (port 5432, user: swet, db: swet)
- 13 tables across auth, onboarding, questions, assessments, and scoring domains
- 12 seeded competency groups with per-role weights
- Async SQLAlchemy with asyncpg driver

## Key Conventions

- Backend: ruff for linting/formatting, mypy for type checking
- Frontend: ESLint + TypeScript strict mode
- Commit titles: lowercase, max 50 characters
- No hardcoded secrets - use .env files
- Tests: SQLite for backend unit tests, MSW for frontend API mocking
- PR descriptions must follow .github/ template

## Specs Reference

All specs live in `specs/` organized by phase:
- `foundation/` - SPEC-001 through SPEC-006 (scaffolding, DB, auth, middleware, errors, tests)
- `core/` - SPEC-010 through SPEC-015 (onboarding, competencies, questions, caching, assessment engine)
- `assessment-ux/` - SPEC-020 through SPEC-024 (renderers, timer, auto-save, uniqueness, navigation)
- `results/` - SPEC-030 through SPEC-034 (grading, computation, visualization, history)
- `polish/` - SPEC-040 through SPEC-043 (performance, resilience, accessibility, rate limiting)
