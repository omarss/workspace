"""Tanzeel AI - FastAPI Backend."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import auth, recognition, progress
from .services.matcher import quran_matcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: load Quran data into matcher
    data_path = os.path.join(os.path.dirname(__file__), "data", "quran.json")
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Quran data not found at {data_path}")
    quran_matcher.load(data_path)
    print(f"Loaded {len(quran_matcher.ayat)} ayat into matcher")
    yield


app = FastAPI(
    title="Tanzeel AI",
    description="Quran Recitation Recognition API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(recognition.router)
app.include_router(progress.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "matcher_loaded": quran_matcher._loaded,
        "ayat_count": len(quran_matcher.ayat),
    }
