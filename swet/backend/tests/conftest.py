"""Shared test fixtures for the backend test suite."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.assessments.models import Answer, Assessment, AssessmentQuestion  # noqa: F401

# Import all models so Base.metadata has all tables for create_all
from src.auth.models import User  # noqa: F401
from src.database import Base, get_db
from src.main import create_app
from src.onboarding.models import UserProfile  # noqa: F401
from src.questions.models import (  # noqa: F401
    Competency,
    Question,
    QuestionPool,
    RoleCompetencyWeight,
    UserQuestionHistory,
)
from src.scoring.models import AnswerGrade, AssessmentResult, CompetencyScore  # noqa: F401

# Use in-memory SQLite for tests (fast, no external DB needed)
TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    """Create a test database engine with SQLite type adaptations."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    # SQLite needs json1 for JSONB columns - it maps them to TEXT automatically
    # via SQLAlchemy's dialect-specific compilation
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional database session that rolls back after each test."""
    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session, session.begin():
        yield session
        await session.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client with the test DB session."""
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_jwt_payload() -> dict:
    """A mock NextAuth JWT payload for testing authenticated endpoints."""
    return {
        "sub": "12345678",
        "name": "testuser",
        "email": "test@example.com",
        "picture": "https://avatars.githubusercontent.com/u/12345678",
        "login": "testuser",
        "github_id": 12345678,
    }


@pytest.fixture
async def authenticated_client(
    db_session: AsyncSession,
    mock_jwt_payload: dict,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide a test client with a mock authenticated user."""
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # Mock the JWT validation middleware by injecting the payload into request.state
    from starlette.middleware.base import BaseHTTPMiddleware

    class MockAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.jwt = mock_jwt_payload
            return await call_next(request)

    app.add_middleware(MockAuthMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def anonymous_client(
    db_session: AsyncSession,
) -> AsyncGenerator[tuple[AsyncClient, str], None]:
    """Provide a test client with an anonymous user session.

    Returns a tuple of (client, token) so tests can use the Bearer token.
    """
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create anonymous session via the endpoint
        response = await ac.post("/api/v1/auth/anonymous")
        assert response.status_code == 200
        data = response.json()
        token = data["token"]

        # Return client with auth header pre-configured
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac, token
