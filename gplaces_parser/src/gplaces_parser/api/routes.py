"""/v1/places — see FEEDBACK.md §3."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from ..categories import ALLOWED_SLUGS
from ..config import settings
from ..db import connection
from . import queries
from .deps import AuthDep
from .schemas import NearbyResponse, NearbyResult

router = APIRouter(prefix="/v1")


@router.get(
    "/places",
    response_model=NearbyResponse,
    responses={401: {}, 400: {}},
)
async def nearby(
    _: AuthDep,
    lat: Annotated[float, Query(ge=-90.0, le=90.0)],
    lon: Annotated[float, Query(ge=-180.0, le=180.0)],
    radius: Annotated[int, Query(ge=1, le=50_000)],
    category: Annotated[str, Query()],
    limit: Annotated[int | None, Query(ge=1)] = None,
    lang: Annotated[str, Query(pattern="^(ar|en)$")] = "en",
) -> NearbyResponse:
    slug = category.strip().lower()
    if slug not in ALLOWED_SLUGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown category: {category}",
        )

    effective_limit = min(
        limit if limit is not None else settings.api_default_limit,
        settings.api_max_limit,
    )

    with connection() as conn:
        rows = queries.nearby(
            conn,
            lat=lat,
            lon=lon,
            radius_m=radius,
            category=slug,
            limit=effective_limit,
        )

    results = [
        NearbyResult(
            id=r["place_id"],
            name=r["name"],
            name_ar=r["name"],  # scraped in ar; omono's parser tolerates both = same
            category=r["category"],
            lat=r["latitude"],
            lon=r["longitude"],
            address=r["full_address"],
            phone=r["phone"],
            rating=float(r["rating"]) if r["rating"] is not None else None,
            review_count=r["reviews_count"],
            open_now=None,  # derived from working_hours — not yet parsed
            website=r["website"],
        )
        for r in rows
    ]

    return NearbyResponse(
        results=results,
        source="gplaces",
        generated_at=datetime.now(UTC),
    )


@router.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    # No auth — used by k8s liveness/readiness probes.
    return {"status": "ok"}
