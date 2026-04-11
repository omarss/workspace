"""FastAPI application factory for the SWET API."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from swet_api.auth.router import router as auth_router
from swet_api.db import get_db
from swet_api.routers.assessments import router as assessments_router
from swet_api.routers.attempts import router as attempts_router
from swet_api.routers.bookmarks import router as bookmarks_router
from swet_api.routers.dashboard import router as dashboard_router
from swet_api.routers.preferences import router as preferences_router
from swet_api.routers.questions import router as questions_router
from swet_api.routers.reviews import router as reviews_router
from swet_api.routers.sessions import router as sessions_router
from swet_api.routers.stats import router as stats_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialize database on startup."""
    # Ensure the database and schema exist
    conn = get_db()
    conn.close()
    yield


app = FastAPI(
    title="SWET API",
    description="REST API for the Software Engineering Training assessment tool",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow all origins in development, configure for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(preferences_router)
app.include_router(questions_router)
app.include_router(attempts_router)
app.include_router(stats_router)
app.include_router(bookmarks_router)
app.include_router(assessments_router)
app.include_router(sessions_router)
app.include_router(reviews_router)
app.include_router(dashboard_router)


@app.get("/health")
def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
