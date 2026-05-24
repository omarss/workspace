"""Geo repo — Saudi-Arabia regions + cities + fuzzy city lookup."""

from __future__ import annotations

from ..models import SaCity, SaRegion
from .base import Repo


class GeoRepo(Repo):
    async def list_regions(self) -> list[SaRegion]:
        rows = await self._fetchall("SELECT * FROM sa_regions ORDER BY name_en")
        return self._to_models(SaRegion, rows)

    async def list_cities(self, *, region_code: str | None = None) -> list[SaCity]:
        if region_code:
            rows = await self._fetchall(
                "SELECT * FROM sa_cities WHERE region_code = %(r)s ORDER BY name_en",
                {"r": region_code},
            )
        else:
            rows = await self._fetchall("SELECT * FROM sa_cities ORDER BY name_en")
        return self._to_models(SaCity, rows)

    async def upsert_region(
        self,
        *,
        code: str,
        name_en: str,
        name_ar: str,
    ) -> SaRegion:
        row = await self._fetchone(
            """
            INSERT INTO sa_regions (code, name_en, name_ar)
            VALUES (%(c)s, %(en)s, %(ar)s)
            ON CONFLICT (code) DO UPDATE SET
                name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar
            RETURNING *;
            """,
            {"c": code, "en": name_en, "ar": name_ar},
        )
        assert row is not None
        return SaRegion.model_validate(row)

    async def upsert_city(
        self,
        *,
        region_code: str,
        name_en: str,
        name_ar: str,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> SaCity:
        row = await self._fetchone(
            """
            INSERT INTO sa_cities (region_code, name_en, name_ar, latitude, longitude)
            VALUES (%(r)s, %(en)s, %(ar)s, %(lat)s, %(lon)s)
            ON CONFLICT (region_code, name_en) DO UPDATE SET
                name_ar = EXCLUDED.name_ar,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude
            RETURNING *;
            """,
            {"r": region_code, "en": name_en, "ar": name_ar, "lat": latitude, "lon": longitude},
        )
        assert row is not None
        return SaCity.model_validate(row)

    async def find_city(
        self,
        query: str,
        *,
        region_code: str | None = None,
        min_similarity: float = 0.4,
        limit: int = 5,
    ) -> list[tuple[SaCity, float]]:
        """Fuzzy lookup across name_en + name_ar with normalize_text."""
        rows = await self._fetchall(
            """
            WITH q AS (SELECT normalize_text(%(q)s) AS nq)
            SELECT c.*, GREATEST(
                similarity(normalize_en(c.name_en), q.nq),
                similarity(normalize_ar(c.name_ar), q.nq)
            ) AS sim
            FROM sa_cities c, q
            WHERE (%(r)s::text IS NULL OR c.region_code = %(r)s)
              AND (
                  normalize_en(c.name_en) %% q.nq
               OR normalize_ar(c.name_ar) %% q.nq
              )
            ORDER BY sim DESC
            LIMIT %(lim)s;
            """,
            {"q": query, "r": region_code, "lim": limit},
        )
        kept: list[tuple[SaCity, float]] = []
        for row in rows:
            sim = float(row.pop("sim"))
            if sim >= min_similarity:
                kept.append((SaCity.model_validate(row), sim))
        return kept
