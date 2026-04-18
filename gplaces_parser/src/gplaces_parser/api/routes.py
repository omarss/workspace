"""/v1/places — see FEEDBACK.md §3."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from ..categories import ALLOWED_SLUGS
from ..config import settings
from ..db import connection
from . import queries, review_search_queries, roads_queries, search_queries
from .deps import AuthDep
from .schemas import (
    NearbyResponse,
    NearbyResult,
    Pagination,
    ReviewHit,
    ReviewPlace,
    ReviewSearchResponse,
    Road,
    RoadsResponse,
    SearchResponse,
    SearchResult,
)

router = APIRouter(prefix="/v1")


def _cid_decimal(place_id: str | None) -> str | None:
    """Extract the decimal CID from a `0x<fid>:0x<cid>` place_id.

    Returns the second hex chunk as a decimal string (u64-safe). Clients
    compose `https://www.google.com/maps?cid=<cid>` deep links with it
    without having to parse the compound id themselves (FEEDBACK §9.3).
    """
    if not place_id or ":" not in place_id:
        return None
    try:
        _, tail = place_id.split(":", 1)
        return str(int(tail, 16))
    except ValueError:
        return None


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
    category: Annotated[str, Query(description="slug, 'all', or comma-separated list")],
    limit: Annotated[int | None, Query(ge=1)] = None,
    lang: Annotated[str, Query(pattern="^(ar|en)$")] = "en",
    min_rating: Annotated[float, Query(ge=0.0, le=5.0)] = 0.0,
    min_reviews: Annotated[int, Query(ge=0)] = 0,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> NearbyResponse:
    # FEEDBACK §9.1: `category=all` disables the filter; comma-separated
    # lists union several slugs into one call. Back-compat preserved —
    # a single slug behaves exactly as before.
    raw = category.strip().lower()
    categories: list[str] | None
    if raw == "all":
        categories = None
    else:
        slugs = [s.strip() for s in raw.split(",") if s.strip()]
        unknown = [s for s in slugs if s not in ALLOWED_SLUGS]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown category: {','.join(unknown)}",
            )
        categories = slugs

    effective_limit = min(
        limit if limit is not None else settings.api_default_limit,
        settings.api_max_limit,
    )

    with connection() as conn:
        rows, has_more = queries.nearby(
            conn,
            lat=lat,
            lon=lon,
            radius_m=radius,
            categories=categories,
            limit=effective_limit,
            min_rating=min_rating,
            min_reviews=min_reviews,
            offset=offset,
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
                cid=_cid_decimal(r["place_id"]),
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
        pagination=Pagination(
            offset=offset,
            limit=effective_limit,
            next_offset=(offset + effective_limit) if has_more else None,
            has_more=has_more,
        ),
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
    snap_m: Annotated[int, Query(ge=0, le=200)] = 0,
) -> RoadsResponse:
    """Return every road polygon that contains (lat, lon).

    Multiple roads come back at intersections / overlapping carriageways;
    the client picks. Primary ranking is by highway class (motorway first)
    then by polygon area ascending, so the most specific / smallest road
    a point belongs to appears first within its class.
    """
    with connection() as conn:
        rows = roads_queries.at_point(
            conn, lat=lat, lon=lon, limit=limit, snap_m=snap_m
        )
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
            heading_deg=r.get("heading_deg"),
            snapped=bool(r.get("snapped", False)),
            snap_distance_m=float(r.get("snap_distance_m", 0.0)),
        )
        for r in rows
    ]
    return RoadsResponse(
        roads=results,
        source="gplaces",
        generated_at=datetime.now(UTC),
    )


@router.get(
    "/search",
    response_model=SearchResponse,
    responses={401: {}, 400: {}},
)
async def search(
    _: AuthDep,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    category: Annotated[str | None, Query()] = None,
    lat: Annotated[float | None, Query(ge=-90.0, le=90.0)] = None,
    lon: Annotated[float | None, Query(ge=-180.0, le=180.0)] = None,
    radius: Annotated[int | None, Query(ge=1, le=50_000)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    lang: Annotated[str, Query(pattern="^(ar|en)$")] = "en",
    min_rating: Annotated[float, Query(ge=0.0, le=5.0)] = 0.0,
    min_reviews: Annotated[int, Query(ge=0)] = 0,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> SearchResponse:
    """Keyword + fuzzy search over places.

    `q` is free text (Arabic or English); matched via Postgres FTS on
    name/category/address plus trigram similarity on names for typo
    tolerance. Optional filters:
      - `category` — slug from the /v1/places enum
      - `lat` + `lon` + `radius` — bounding-box prefilter in metres

    Results are sorted by relevance score. Ties break on review count.
    """
    slug: str | None = None
    if category is not None:
        slug = category.strip().lower()
        if slug not in ALLOWED_SLUGS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown category: {category}",
            )

    geo_args = (lat, lon, radius)
    if any(v is not None for v in geo_args) and not all(v is not None for v in geo_args):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="lat, lon, radius must all be provided together",
        )

    with connection() as conn:
        rows, has_more = search_queries.search(
            conn,
            q=q,
            category=slug,
            lat=lat,
            lon=lon,
            radius_m=radius,
            limit=limit,
            min_rating=min_rating,
            min_reviews=min_reviews,
            offset=offset,
        )

    def pick_name(row: dict) -> tuple[str, str | None]:
        ar, en = row["name"], row["name_en"]
        if lang == "ar":
            return (ar or en or "", ar)
        return (en or ar or "", ar)

    def pick_addr(row: dict) -> str | None:
        if lang == "ar":
            return row["full_address"] or row["full_address_en"]
        return row["full_address_en"] or row["full_address"]

    results: list[SearchResult] = []
    for r in rows:
        name_primary, name_ar = pick_name(r)
        results.append(
            SearchResult(
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
                open_now=r["open_now"],
                website=r["website"],
                score=round(float(r["score"]), 4),
            )
        )

    return SearchResponse(
        results=results,
        query=q,
        pagination=Pagination(
            offset=offset,
            limit=limit,
            next_offset=(offset + limit) if has_more else None,
            has_more=has_more,
        ),
        source="gplaces",
        generated_at=datetime.now(UTC),
    )


@router.get(
    "/reviews/search",
    response_model=ReviewSearchResponse,
    responses={401: {}, 400: {}},
)
async def reviews_search(
    _: AuthDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    category: Annotated[str | None, Query(description="slug, 'all', or comma-separated list")] = None,
    place_id: Annotated[str | None, Query()] = None,
    min_rating: Annotated[int, Query(ge=1, le=5)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    lang: Annotated[str, Query(pattern="^(ar|en)$")] = "en",
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> ReviewSearchResponse:
    """Full-text search over review bodies.

    Joins each match to its parent place so the response carries name,
    category, and coordinates. `snippet` wraps matched tokens in
    `<b>…</b>` for UI highlighting.
    """
    categories: list[str] | None = None
    if category is not None:
        raw = category.strip().lower()
        if raw != "all":
            slugs = [s.strip() for s in raw.split(",") if s.strip()]
            unknown = [s for s in slugs if s not in ALLOWED_SLUGS]
            if unknown:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"unknown category: {','.join(unknown)}",
                )
            categories = slugs

    with connection() as conn:
        rows, has_more = review_search_queries.search(
            conn,
            q=q,
            categories=categories,
            place_id=place_id,
            min_review_rating=min_rating,
            limit=limit,
            offset=offset,
        )

    def place_name(ar: str | None, en: str | None) -> tuple[str, str | None]:
        if lang == "ar":
            return (ar or en or "", ar)
        return (en or ar or "", ar)

    results: list[ReviewHit] = []
    for r in rows:
        primary, ar_name = place_name(r["place_name"], r["place_name_en"])
        results.append(
            ReviewHit(
                review_id=r["review_id"],
                rating=r["review_rating"],
                text=r["review_text"],
                snippet=r["snippet"],
                published_at=r["published_at"],
                author=r["author"],
                likes=r["likes"],
                place=ReviewPlace(
                    id=r["place_id"],
                    name=primary,
                    name_ar=ar_name,
                    category=r["place_category"],
                    lat=r["place_lat"],
                    lon=r["place_lon"],
                    rating=float(r["place_rating"]) if r["place_rating"] is not None else None,
                ),
                score=round(float(r["score"]), 4),
            )
        )

    return ReviewSearchResponse(
        results=results,
        query=q,
        pagination=Pagination(
            offset=offset,
            limit=limit,
            next_offset=(offset + limit) if has_more else None,
            has_more=has_more,
        ),
        source="gplaces",
        generated_at=datetime.now(UTC),
    )


@router.get("/admin/usage", include_in_schema=False)
async def admin_usage(_: AuthDep) -> dict:
    """Aggregated API-usage counters per (key_prefix, endpoint, status).

    Authed with the same X-Api-Key (there's only one key right now, so
    a dedicated admin key would be ceremony without benefit). Returns a
    list of rows sorted by total count descending — the caller can
    format as a table however they like.
    """
    sql = """
    SELECT key_prefix,
           endpoint,
           status_bucket,
           SUM(count)::bigint AS total,
           MIN(day)           AS first_day,
           MAX(last_seen)     AS last_seen
    FROM api_usage
    GROUP BY key_prefix, endpoint, status_bucket
    ORDER BY total DESC
    """
    from psycopg.rows import dict_row
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        rows = list(cur.fetchall())
    return {
        "rows": [
            {
                "key_prefix": r["key_prefix"],
                "endpoint": r["endpoint"],
                "status": r["status_bucket"],
                "count": int(r["total"]),
                "first_day": r["first_day"].isoformat() if r["first_day"] else None,
                "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
            }
            for r in rows
        ],
        "source": "gplaces",
        "generated_at": datetime.now(UTC),
    }


@router.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    # No auth — used by k8s liveness/readiness probes.
    return {"status": "ok"}
