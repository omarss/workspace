"""/v1/places — see FEEDBACK.md §3."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from ..categories import ALLOWED_SLUGS
from ..config import settings
from ..db import connection
from . import queries, roads_queries
from .deps import AuthDep
from .schemas import NearbyResponse, NearbyResult, Road, RoadsResponse

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

    # Per FEEDBACK §3 the JSON `name` field is English and `name_ar` is
    # Arabic. If the caller asked for `lang=ar` and only an Arabic name
    # is known, we fall back to it for the English slot too so the
    # client always has something to render.
    def pick_name(row):
        ar, en = row["name"], row["name_en"]
        if lang == "ar":
            return (ar or en, ar or en)
        return (en or ar, ar or en)

    def pick_addr(row):
        if lang == "ar":
            return row["full_address"] or row["full_address_en"]
        return row["full_address_en"] or row["full_address"]

    results = []
    for r in rows:
        name_primary, name_ar = pick_name(r)
        results.append(
            NearbyResult(
                id=r["place_id"],
                name=name_primary,
                name_ar=name_ar,
                category=r["category"],
                lat=r["latitude"],
                lon=r["longitude"],
                address=pick_addr(r),
                phone=r["phone"],
                rating=float(r["rating"]) if r["rating"] is not None else None,
                review_count=r["reviews_count"],
                open_now=None,
                website=r["website"],
            )
        )

    return NearbyResponse(
        results=results,
        source="gplaces",
        generated_at=datetime.now(UTC),
    )


@router.get(
    "/roads",
    response_model=RoadsResponse,
    responses={401: {}, 400: {}},
)
async def roads(
    _: AuthDep,
    lat: Annotated[float, Query(ge=-90.0, le=90.0)],
    lon: Annotated[float, Query(ge=-180.0, le=180.0)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> RoadsResponse:
    """Return every road polygon that contains (lat, lon).

    Multiple roads come back at intersections / overlapping carriageways;
    the client picks. Primary ranking is by highway class (motorway first)
    then by polygon area ascending, so the most specific / smallest road
    a point belongs to appears first within its class.
    """
    with connection() as conn:
        rows = roads_queries.at_point(conn, lat=lat, lon=lon, limit=limit)
    results = [
        Road(
            osm_id=r["osm_id"],
            name=r["name"],
            name_en=r["name_en"],
            highway=r["highway"],
            ref=r["ref"],
            maxspeed_kmh=r["maxspeed_kmh"],
            speed_source=r["speed_source"],
            lanes=r["lanes"],
            oneway=r["oneway"],
        )
        for r in rows
    ]
    return RoadsResponse(
        roads=results,
        source="gplaces",
        generated_at=datetime.now(UTC),
    )


@router.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    # No auth — used by k8s liveness/readiness probes.
    return {"status": "ok"}
