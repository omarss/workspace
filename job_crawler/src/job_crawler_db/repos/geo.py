"""Geo repo — regions + cities + fuzzy city lookup, scoped per country."""

from __future__ import annotations

from ..models import City, Region
from .base import Repo


class GeoRepo(Repo):
    async def list_regions(self, *, country_code: str | None = None) -> list[Region]:
        if country_code:
            rows = await self._fetchall(
                "SELECT * FROM regions WHERE country_code = %(c)s ORDER BY name_en",
                {"c": country_code},
            )
        else:
            rows = await self._fetchall(
                "SELECT * FROM regions ORDER BY country_code, name_en",
            )
        return self._to_models(Region, rows)

    async def list_cities(
        self,
        *,
        country_code: str | None = None,
        region_code: str | None = None,
    ) -> list[City]:
        rows = await self._fetchall(
            """
            SELECT * FROM cities
            WHERE (%(c)s::char(2) IS NULL OR country_code = %(c)s)
              AND (%(r)s::text    IS NULL OR region_code  = %(r)s)
            ORDER BY country_code, name_en;
            """,
            {"c": country_code, "r": region_code},
        )
        return self._to_models(City, rows)

    async def upsert_region(
        self,
        *,
        code: str,
        name_en: str,
        name_ar: str,
        country_code: str = "sa",
    ) -> Region:
        row = await self._fetchone(
            """
            INSERT INTO regions (country_code, code, name_en, name_ar)
            VALUES (%(cc)s, %(c)s, %(en)s, %(ar)s)
            ON CONFLICT (country_code, code) DO UPDATE SET
                name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar
            RETURNING *;
            """,
            {"cc": country_code, "c": code, "en": name_en, "ar": name_ar},
        )
        assert row is not None
        return Region.model_validate(row)

    async def upsert_city(
        self,
        *,
        region_code: str,
        name_en: str,
        name_ar: str,
        country_code: str = "sa",
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> City:
        row = await self._fetchone(
            """
            INSERT INTO cities (country_code, region_code, name_en, name_ar, latitude, longitude)
            VALUES (%(cc)s, %(r)s, %(en)s, %(ar)s, %(lat)s, %(lon)s)
            ON CONFLICT (country_code, region_code, name_en) DO UPDATE SET
                name_ar  = EXCLUDED.name_ar,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude
            RETURNING *;
            """,
            {
                "cc": country_code,
                "r": region_code,
                "en": name_en,
                "ar": name_ar,
                "lat": latitude,
                "lon": longitude,
            },
        )
        assert row is not None
        return City.model_validate(row)

    async def find_city(
        self,
        query: str,
        *,
        country_code: str | None = None,
        region_code: str | None = None,
        min_similarity: float = 0.4,
        limit: int = 5,
    ) -> list[tuple[City, float]]:
        """Fuzzy lookup across name_en + name_ar with normalize_text.

        Pass `country_code` to scope to a single country — important for
        ambiguous names that exist in multiple countries (e.g. "Al Rayyan"
        in both Qatar and Saudi Arabia would otherwise collide).
        """
        rows = await self._fetchall(
            """
            WITH q AS (SELECT normalize_text(%(q)s) AS nq)
            SELECT c.*, GREATEST(
                similarity(normalize_en(c.name_en), q.nq),
                similarity(normalize_ar(c.name_ar), q.nq)
            ) AS sim
            FROM cities c, q
            WHERE (%(cc)s::char(2) IS NULL OR c.country_code = %(cc)s)
              AND (%(r)s::text     IS NULL OR c.region_code  = %(r)s)
              AND (
                  normalize_en(c.name_en) %% q.nq
               OR normalize_ar(c.name_ar) %% q.nq
              )
            ORDER BY sim DESC
            LIMIT %(lim)s;
            """,
            {"q": query, "cc": country_code, "r": region_code, "lim": limit},
        )
        kept: list[tuple[City, float]] = []
        for row in rows:
            sim = float(row.pop("sim"))
            if sim >= min_similarity:
                kept.append((City.model_validate(row), sim))
        return kept
