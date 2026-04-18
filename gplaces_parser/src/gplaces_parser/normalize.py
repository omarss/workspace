"""Turn an Outscraper response record into our column layout.

Field names in the API response have drifted over versions (e.g. `site`
vs `website`, `reviews` vs `reviews_count`). We read defensively from a
list of candidate keys and keep the original record in the `raw` column
so nothing is ever lost.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _ts(v: Any) -> datetime | None:
    if v in (None, "", 0):
        return None
    try:
        # Outscraper returns epoch seconds for review timestamps.
        return datetime.fromtimestamp(int(v), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _list(v: Any) -> list[str] | None:
    if v is None:
        return None
    if isinstance(v, list):
        return [str(x) for x in v if x]
    if isinstance(v, str):
        return [v]
    return None


def normalize_place(
    rec: dict[str, Any],
    *,
    category_slug: str,
    query: str,
    tile_lat: float,
    tile_lng: float,
    lang: str = "ar",
) -> dict[str, Any] | None:
    place_id = _first(rec, "place_id", "placeId")
    name = _first(rec, "name", "title")
    if not place_id or not name:
        return None

    # Route the localised fields by language so a single place can carry
    # both `name` / `name_ar`-flavoured columns and `name_en` populated
    # from separate hl=en searches. Pass 1 only produces the name; pass
    # 2's detail extraction can later add addresses per language.
    addr = _first(rec, "full_address", "address")

    return {
        "place_id": str(place_id),
        "google_id": _first(rec, "google_id", "googleId"),
        "cid": _first(rec, "cid"),
        "name": str(name) if lang == "ar" else None,
        "name_en": str(name) if lang == "en" else None,
        "full_address": addr if lang == "ar" else None,
        "full_address_en": addr if lang == "en" else None,
        "borough": _first(rec, "borough"),
        "street": _first(rec, "street"),
        "city": _first(rec, "city"),
        "postal_code": _first(rec, "postal_code", "postalCode"),
        "country": _first(rec, "country"),
        "latitude": _first(rec, "latitude", "lat"),
        "longitude": _first(rec, "longitude", "lng", "lon"),
        "phone": _first(rec, "phone", "phone_1"),
        "website": _first(rec, "site", "website"),
        "rating": _first(rec, "rating"),
        "reviews_count": _int(_first(rec, "reviews", "reviews_count")),
        "reviews_per_score": _first(rec, "reviews_per_score", "rating_histogram"),
        "photos_count": _int(_first(rec, "photos_count", "photos")),
        "price_level": _first(rec, "range", "price_level"),
        "category": category_slug,
        "subcategories": _list(_first(rec, "subtypes", "categories", "types")),
        "working_hours": _first(rec, "working_hours", "hours"),
        "popular_times": _first(rec, "popular_times", "popularTimes"),
        "plus_code": _first(rec, "plus_code", "plusCode"),
        "bounds": _first(rec, "bounds", "viewport"),
        "service_area": _first(rec, "service_area", "service_areas", "area_service"),
        "verified": _first(rec, "verified"),
        "business_status": _first(rec, "business_status", "status"),
        "open_now": _first(rec, "open_now"),
        "hours_snippet": _first(rec, "hours_snippet"),
        "google_url": _first(rec, "google_url", "location_link", "url"),
        "query": query,
        "tile_lat": tile_lat,
        "tile_lng": tile_lng,
        "raw": rec,
    }


def normalize_review(rec: dict[str, Any], *, place_id: str) -> dict[str, Any] | None:
    review_id = _first(rec, "review_id", "reviewId")
    if not review_id:
        return None

    return {
        "review_id": str(review_id),
        "place_id": place_id,
        "author_title": _first(rec, "author_title", "autor_title", "author_name"),
        "author_id": _first(rec, "author_id"),
        "author_url": _first(rec, "author_url", "author_link"),
        "author_reviews_count": _int(_first(rec, "author_reviews_count")),
        "author_ratings_count": _int(_first(rec, "author_ratings_count")),
        "rating": _int(_first(rec, "review_rating", "rating")),
        "text": _first(rec, "review_text", "text"),
        "text_translated": _first(rec, "review_text_translated", "owner_answer_translated"),
        "language": _first(rec, "review_language", "language"),
        "published_at": _ts(_first(rec, "review_timestamp", "published_at_timestamp")),
        "likes": _int(_first(rec, "review_likes", "likes")),
        "owner_answer": _first(rec, "owner_answer", "owner_response"),
        "owner_answer_at": _ts(_first(rec, "owner_answer_timestamp")),
        "photos": _first(rec, "review_photos", "photos", "owner_answer_photos"),
        "raw": rec,
    }
