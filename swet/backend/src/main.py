from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    yield
    # Shutdown
    from src.database import engine

    await engine.dispose()


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url="/api/redoc" if not settings.is_production else None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    from src.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(RateLimitMiddleware)

    # Register exception handlers
    from src.errors import register_exception_handlers

    register_exception_handlers(app)

    # Register routers
    from src.assessments.router import router as assessments_router
    from src.auth.router import router as auth_router
    from src.onboarding.router import router as onboarding_router
    from src.questions.router import router as questions_router
    from src.scoring.router import router as scoring_router

    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(onboarding_router, prefix="/api/v1/onboarding", tags=["onboarding"])
    app.include_router(questions_router, prefix="/api/v1/questions", tags=["questions"])
    app.include_router(assessments_router, prefix="/api/v1/assessments", tags=["assessments"])
    app.include_router(scoring_router, prefix="/api/v1/results", tags=["results"])

    @app.get("/api/health")
    async def health_check() -> dict[str, str]:
        return {"status": "healthy", "version": settings.app_version}

    return app


app = create_app()
