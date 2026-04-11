# SPEC-006: Test Infrastructure

## Status
Approved

## Priority
P0

## Dependencies
- SPEC-001

## Overview
Establish the complete test infrastructure for both backend and frontend, enabling reliable and fast test execution from day one. This spec covers the backend pytest configuration (async SQLite test database, fixtures, mock JWT, Factory Boy factories), the frontend Vitest configuration (jsdom, React Testing Library, MSW handlers), and the Playwright E2E configuration. Coverage thresholds are enforced to maintain quality as the codebase grows.

## Requirements

### Functional
1. Backend `conftest.py` with async SQLite in-memory test database, async session fixture, and test client fixture
2. Backend mock JWT fixture that bypasses `fastapi-nextauth-jwt` validation and injects a known user
3. Factory Boy factories for all 13 database models with sensible defaults
4. Backend test markers: `@pytest.mark.integration` for tests requiring a real database
5. Frontend Vitest configuration with jsdom environment, React Testing Library, and `@testing-library/jest-dom` matchers
6. Frontend MSW (Mock Service Worker) handlers for all backend API endpoints
7. Playwright configuration for E2E tests targeting `http://localhost:3000`
8. Coverage reporting for both backend (pytest-cov) and frontend (vitest --coverage)

### Non-Functional
1. Backend test suite runs in under 10 seconds for unit tests (SQLite, no network)
2. Frontend unit test suite runs in under 15 seconds
3. Backend coverage threshold: 85% (enforced via `pyproject.toml`)
4. Frontend coverage threshold: 80% (enforced via Vitest config)
5. Tests are isolated -- no shared state between test functions
6. Test database is created fresh for each test session (or transaction-rolled-back per test)

## Technical Design

### Backend Test Configuration

**`tests/conftest.py`**
```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from httpx import AsyncClient, ASGITransport

from src.database import Base
from src.main import app
from src.dependencies import get_db, get_current_user

# Async SQLite engine for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
async def engine():
    """Create async SQLite engine and tables once per session."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.fixture
async def db_session(engine):
    """Yield a transactional session that rolls back after each test."""
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        async with session.begin():
            yield session
            await session.rollback()

@pytest.fixture
async def client(db_session, mock_user):
    """Yield an httpx AsyncClient with dependency overrides."""
    async def override_get_db():
        yield db_session

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()

@pytest.fixture
def mock_user():
    """Return a mock User instance for authenticated requests."""
    return UserFactory.build()
```

### Factory Boy Factories (`tests/factories.py`)

```python
import factory
from uuid import uuid4
from datetime import datetime, timezone

class UserFactory(factory.Factory):
    class Meta:
        model = User  # from src.auth.models

    id = factory.LazyFunction(uuid4)
    github_id = factory.Sequence(lambda n: n + 1000)
    github_username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.github_username}@test.com")
    avatar_url = factory.LazyAttribute(lambda o: f"https://avatars.test/{o.github_id}")
    is_active = True
    onboarding_completed = False
    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))

class UserProfileFactory(factory.Factory):
    class Meta:
        model = UserProfile

    id = factory.LazyFunction(uuid4)
    user_id = factory.LazyFunction(uuid4)
    primary_role = "backend"
    interests = ["web_development"]
    technologies = {"languages": ["python"], "frameworks": ["fastapi"]}
    experience_years = 3
    config_hash = factory.LazyFunction(lambda: uuid4().hex)

class CompetencyFactory(factory.Factory):
    class Meta:
        model = Competency

    id = factory.Sequence(lambda n: n + 1)
    name = factory.Sequence(lambda n: f"Competency {n}")
    slug = factory.Sequence(lambda n: f"competency_{n}")
    description = factory.Faker("paragraph")
    category = "transferable"

class QuestionPoolFactory(factory.Factory):
    class Meta:
        model = QuestionPool

    id = factory.LazyFunction(uuid4)
    config_hash = factory.LazyFunction(lambda: uuid4().hex[:64])
    competency_id = 1
    difficulty = 3
    format = "mcq"
    total_questions = 20
    generation_status = "complete"

class QuestionFactory(factory.Factory):
    class Meta:
        model = Question

    id = factory.LazyFunction(uuid4)
    pool_id = factory.LazyFunction(uuid4)
    competency_id = 1
    format = "mcq"
    difficulty = 3
    title = "Sample question"
    body = "What is the best answer?"
    options = {"A": "Opt A", "B": "Opt B", "C": "Opt C", "D": "Opt D"}
    correct_answer = "A"

class AssessmentFactory(factory.Factory):
    class Meta:
        model = Assessment

    id = factory.LazyFunction(uuid4)
    user_id = factory.LazyFunction(uuid4)
    config_hash = factory.LazyFunction(lambda: uuid4().hex[:64])
    status = "in_progress"
    total_questions = 100
    current_question_index = 0
    is_timed = False
    time_limit_minutes = None
    started_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))

# Additional factories: AssessmentQuestionFactory, AnswerFactory,
# AssessmentResultFactory, CompetencyScoreFactory, AnswerGradeFactory,
# RoleCompetencyWeightFactory, UserQuestionHistoryFactory
```

### Frontend Test Configuration

**`vitest.config.ts`**
```typescript
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      exclude: ['node_modules/', '.next/', 'tests/'],
      thresholds: { lines: 80, branches: 80, functions: 80, statements: 80 },
    },
  },
});
```

**`tests/setup.ts`**
```typescript
import '@testing-library/jest-dom';
import { server } from './mocks/server';

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

### MSW Mock Handlers (`tests/mocks/handlers.ts`)
```typescript
import { http, HttpResponse } from 'msw';

export const handlers = [
  // Auth
  http.get('/api/v1/auth/me', () =>
    HttpResponse.json({
      id: 'test-uuid',
      github_id: 1001,
      github_username: 'test-user',
      email: 'test@test.com',
      avatar_url: null,
      is_active: true,
      onboarding_completed: true,
      created_at: '2026-01-01T00:00:00Z',
    })
  ),

  // Onboarding
  http.get('/api/v1/onboarding/profile', () => HttpResponse.json(null)),
  http.post('/api/v1/onboarding/profile', () => HttpResponse.json({ id: 'profile-uuid' })),

  // Assessments
  http.get('/api/v1/assessments', () => HttpResponse.json([])),
  http.post('/api/v1/assessments', () => HttpResponse.json({ id: 'assessment-uuid' })),

  // Results
  http.get('/api/v1/results/:id', () =>
    HttpResponse.json({ overall_score: 75.0, overall_proficiency_level: 2, proficiency_label: 'intermediate' })
  ),
];
```

**`tests/mocks/server.ts`**
```typescript
import { setupServer } from 'msw/node';
import { handlers } from './handlers';

export const server = setupServer(...handlers);
```

### Playwright Configuration (`playwright.config.ts`)
```typescript
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30000,
  retries: 1,
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'pnpm dev',
    port: 3000,
    reuseExistingServer: true,
  },
});
```

### Test Directory Structure
```
backend/
  tests/
    conftest.py
    factories.py
    auth/
      test_service.py
      test_router.py
    onboarding/
      test_service.py
      test_router.py
    assessments/
      test_service.py
      test_router.py
    scoring/
      test_service.py
      test_router.py

app/
  tests/
    setup.ts
    mocks/
      handlers.ts
      server.ts
    components/
      auth/
      layout/
      ui/
    lib/
      api/
      stores/
    e2e/
      auth.spec.ts
      onboarding.spec.ts
      assessment.spec.ts
```

## Implementation Notes
- Backend tests use SQLite (via `aiosqlite`) for speed and isolation. SQLite does not support all PostgreSQL features (e.g., `JSON` column behaves differently), so integration tests against PostgreSQL should be marked with `@pytest.mark.integration` and run separately.
- The `db_session` fixture uses a transaction that is rolled back after each test, ensuring complete isolation without recreating tables.
- `app.dependency_overrides` is the FastAPI-native way to inject test doubles. It must be cleared after each test client session.
- Factory Boy's `factory.Factory` (not `SQLAlchemyModelFactory`) is used since we work with async sessions -- models are built in memory and explicitly added to the session when needed.
- MSW v2 uses the `http` and `HttpResponse` API (not the legacy `rest` API). Handlers should match the actual backend URL patterns.
- Playwright `webServer` config auto-starts the dev server if not running, with `reuseExistingServer: true` to skip startup if already running.
- The `asyncio_mode = "auto"` setting in `pyproject.toml` means all async test functions are automatically detected -- no need for `@pytest.mark.asyncio` on each test.

## Testing Strategy
- Unit tests for: Factory defaults produce valid model instances, conftest fixtures create working sessions and clients, MSW handlers return expected mock data
- Integration tests for: Full request cycle through test client with mocked auth, Database operations via test session with rollback isolation
- E2E tests for: Playwright config launches browser and connects to dev server

## Acceptance Criteria
- [ ] `make test` in `backend/` runs pytest with SQLite and all tests pass
- [ ] `make test` in `app/` runs Vitest with jsdom and all tests pass
- [ ] `make test-cov` in `backend/` reports coverage >= 85% (once implementation specs are complete)
- [ ] `make test-cov` in `app/` reports coverage >= 80% (once implementation specs are complete)
- [ ] Backend test client correctly overrides `get_db` and `get_current_user` dependencies
- [ ] Backend mock JWT fixture provides a known user without real JWT validation
- [ ] Factory Boy factories exist for all 13 models and produce valid instances
- [ ] Frontend MSW handlers intercept API calls and return mock data
- [ ] Vitest setup file initializes `@testing-library/jest-dom` matchers and MSW server
- [ ] Playwright config targets `http://localhost:3000` with trace and screenshot on failure
- [ ] No test shares state with another test -- all tests pass in any execution order
- [ ] `make test-e2e` in `app/` runs Playwright tests (once E2E tests are written)
