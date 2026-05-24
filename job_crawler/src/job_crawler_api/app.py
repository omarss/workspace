"""FastAPI app factory + routes.

Run locally:
    uvicorn job_crawler_api.app:app --reload --port 8080

The factory pattern (`create_app`) lets tests inject a custom JobCrawlerDB
without going through env variables.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from job_crawler_db import (
    EmploymentType,
    ExperienceLevel,
    JobCrawlerDB,
    WorkArrangement,
)

_LOG: Final = logging.getLogger(__name__)
_STATIC_DIR: Final = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app(db: JobCrawlerDB | None = None) -> FastAPI:
    """Build the FastAPI app.

    Pass a pre-constructed `db` for tests; production uses `from_env()`.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Lazy: only build a DB if one wasn't injected.
        owned = db is None
        instance = db or JobCrawlerDB.from_env()
        if owned:
            await instance.open()
        app.state.db = instance
        try:
            yield
        finally:
            if owned:
                await instance.close()

    app = FastAPI(
        title="job-crawler-api",
        version="0.1.0",
        description="Read-only API for the job_crawler dataset.",
        docs_url="/v1/docs",
        redoc_url=None,
        openapi_url="/v1/openapi.json",
        lifespan=lifespan,
    )

    # Static dashboard.
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # -------------------------- dashboard ------------------------------
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index() -> str:
        index_path = _STATIC_DIR / "index.html"
        if not index_path.is_file():
            return "<h1>job-crawler-api</h1><p>Static dashboard not packaged.</p>"
        return index_path.read_text("utf-8")

    # -------------------------- health ---------------------------------
    @app.get("/v1/health")
    async def health(request: Request) -> dict[str, Any]:
        """Liveness + DB reachability."""
        db_: JobCrawlerDB = request.app.state.db
        try:
            sources = await db_.sources.list()
            return {"status": "ok", "sources_count": len(sources)}
        except Exception as exc:
            _LOG.exception("health check failed")
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/v1/health/sources")
    async def sources_health(request: Request) -> list[dict[str, Any]]:
        """Per-source crawler health rollup (joins crawler_health when present)."""
        db_: JobCrawlerDB = request.app.state.db
        sources = await db_.sources.list()
        return [
            {
                "slug": s.slug,
                "display_name": s.display_name,
                "kind": s.kind.value,
                "enabled": s.crawl_enabled,
                "trust_weight": float(s.trust_weight),
            }
            for s in sources
        ]

    # -------------------------- search ---------------------------------
    @app.get("/v1/search")
    async def search(
        request: Request,
        q: str | None = Query(default=None, description="Free-text query, EN/AR/mixed"),
        city: str | None = Query(default=None, description="SA city name (fuzzy)"),
        region: str | None = Query(default=None, description="SA region code"),
        employment_type: EmploymentType | None = None,
        work_arrangement: WorkArrangement | None = None,
        experience_level: ExperienceLevel | None = None,
        min_salary: float | None = Query(default=None, ge=0),
        max_salary: float | None = Query(default=None, ge=0),
        saudi_only: bool | None = None,
        limit: int = Query(default=25, le=100, ge=1),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        """Ranked search across the cluster feed."""
        db_: JobCrawlerDB = request.app.state.db
        city_id: UUID | None = None
        if city:
            matches = await db_.geo.find_city(city, limit=1)
            city_id = matches[0][0].id if matches else None

        hits = await db_.search.find_jobs(
            query=q,
            city_id=city_id,
            region_code=region,
            employment_type=employment_type,
            work_arrangement=work_arrangement,
            experience_level=experience_level,
            min_salary=min_salary,
            max_salary=max_salary,
            saudi_nationals_only=saudi_only,
            limit=limit,
            offset=offset,
        )
        return {
            "query": q,
            "count": len(hits),
            "results": [
                {
                    "id": str(h.job.id),
                    "title_en": h.job.title_en,
                    "title_ar": h.job.title_ar,
                    "company_id": str(h.job.company_id) if h.job.company_id else None,
                    "city_id": str(h.job.city_id) if h.job.city_id else None,
                    "employment_type": h.job.employment_type.value
                    if h.job.employment_type
                    else None,
                    "work_arrangement": h.job.work_arrangement.value
                    if h.job.work_arrangement
                    else None,
                    "salary_min": float(h.job.salary_min) if h.job.salary_min else None,
                    "salary_max": float(h.job.salary_max) if h.job.salary_max else None,
                    "salary_currency": h.job.salary_currency,
                    "posting_count": h.job.posting_count,
                    "last_seen_at": h.job.last_seen_at.isoformat(),
                    "score": h.score,
                    "matched_terms": h.matched_terms,
                }
                for h in hits
            ],
        }

    # -------------------------- companies ------------------------------
    @app.get("/v1/companies")
    async def companies(
        request: Request,
        q: str = Query(..., min_length=1, description="Company name (EN/AR, fuzzy)"),
        limit: int = Query(default=10, le=50, ge=1),
    ) -> list[dict[str, Any]]:
        db_: JobCrawlerDB = request.app.state.db
        hits = await db_.companies.find_by_name(q, limit=limit)
        return [
            {
                "id": str(c.id),
                "name_en": c.name_en,
                "name_ar": c.name_ar,
                "website": c.website,
                "linkedin_url": c.linkedin_url,
                "is_verified": c.is_verified,
                "similarity": sim,
            }
            for c, sim in hits
        ]

    # -------------------------- job details ----------------------------
    @app.get("/v1/jobs/{job_id}")
    async def job_detail(request: Request, job_id: UUID) -> dict[str, Any]:
        db_: JobCrawlerDB = request.app.state.db
        job = await db_.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        skills = await db_.jobs.list_skills(job_id)
        locations = await db_.job_locations.list_for_job(job_id)
        company = await db_.companies.get(job.company_id) if job.company_id else None
        return {
            "id": str(job.id),
            "title_en": job.title_en,
            "title_ar": job.title_ar,
            "description_en": job.description_en,
            "description_ar": job.description_ar,
            "company": {
                "id": str(company.id),
                "name_en": company.name_en,
                "name_ar": company.name_ar,
                "website": company.website,
            }
            if company
            else None,
            "employment_type": job.employment_type.value if job.employment_type else None,
            "work_arrangement": job.work_arrangement.value if job.work_arrangement else None,
            "experience_level": job.experience_level.value if job.experience_level else None,
            "hybrid_days_per_week": job.hybrid_days_per_week,
            "salary_min": float(job.salary_min) if job.salary_min else None,
            "salary_max": float(job.salary_max) if job.salary_max else None,
            "salary_currency": job.salary_currency,
            "salary_period": job.salary_period.value if job.salary_period else None,
            "hiring_manager_linkedin_url": job.hiring_manager_linkedin_url,
            "locations": [
                {
                    "city_id": str(loc.city_id) if loc.city_id else None,
                    "region_code": loc.region_code,
                    "office_address": loc.office_address,
                    "is_primary": loc.is_primary,
                }
                for loc in locations
            ],
            "skills": [
                {
                    "id": str(skill.id),
                    "name_en": skill.name_en,
                    "name_ar": skill.name_ar,
                    "kind": skill.kind.value,
                    "requirement": link.requirement.value,
                    "proficiency": link.proficiency_level.value if link.proficiency_level else None,
                    "min_years": link.min_years,
                    "importance": float(link.importance),
                }
                for link, skill in skills
            ],
            "verdict": job.verdict.value,
            "legit_score": float(job.legit_score) if job.legit_score else None,
            "posting_count": job.posting_count,
            "first_seen_at": job.first_seen_at.isoformat(),
            "last_seen_at": job.last_seen_at.isoformat(),
        }

    return app


# Default app for `uvicorn job_crawler_api.app:app` invocation.
app = create_app()
