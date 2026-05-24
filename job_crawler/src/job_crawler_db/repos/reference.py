"""Reference repo — industries, job categories, countries (lookup tables)."""

from __future__ import annotations

from ..models import Country, Industry, JobCategory
from .base import Repo


class ReferenceRepo(Repo):
    # -- countries -------------------------------------------------------

    async def list_countries(self) -> list[Country]:
        rows = await self._fetchall("SELECT * FROM countries ORDER BY code")
        return self._to_models(Country, rows)

    async def upsert_country(
        self,
        *,
        code: str,
        name_en: str,
        name_ar: str,
        dial_code: str,
        currency: str,
    ) -> Country:
        row = await self._fetchone(
            """
            INSERT INTO countries (code, name_en, name_ar, dial_code, currency)
            VALUES (%(c)s, %(en)s, %(ar)s, %(d)s, %(cur)s)
            ON CONFLICT (code) DO UPDATE SET
                name_en = EXCLUDED.name_en,
                name_ar = EXCLUDED.name_ar,
                dial_code = EXCLUDED.dial_code,
                currency = EXCLUDED.currency
            RETURNING *;
            """,
            {"c": code, "en": name_en, "ar": name_ar, "d": dial_code, "cur": currency},
        )
        assert row is not None
        return Country.model_validate(row)

    # -- industries ------------------------------------------------------

    async def list_industries(self) -> list[Industry]:
        rows = await self._fetchall("SELECT * FROM industries ORDER BY code")
        return self._to_models(Industry, rows)

    async def upsert_industry(
        self,
        *,
        code: str,
        name_en: str,
        name_ar: str,
        isic_code: str | None = None,
    ) -> Industry:
        row = await self._fetchone(
            """
            INSERT INTO industries (code, name_en, name_ar, isic_code)
            VALUES (%(c)s, %(en)s, %(ar)s, %(isic)s)
            ON CONFLICT (code) DO UPDATE SET
                name_en = EXCLUDED.name_en,
                name_ar = EXCLUDED.name_ar,
                isic_code = EXCLUDED.isic_code
            RETURNING *;
            """,
            {"c": code, "en": name_en, "ar": name_ar, "isic": isic_code},
        )
        assert row is not None
        return Industry.model_validate(row)

    # -- job categories --------------------------------------------------

    async def list_categories(
        self,
        *,
        parent_code: str | None = None,
    ) -> list[JobCategory]:
        if parent_code is None:
            rows = await self._fetchall(
                "SELECT * FROM job_categories WHERE parent_code IS NULL ORDER BY code",
            )
        else:
            rows = await self._fetchall(
                "SELECT * FROM job_categories WHERE parent_code = %(p)s ORDER BY code",
                {"p": parent_code},
            )
        return self._to_models(JobCategory, rows)

    async def get_category(self, code: str) -> JobCategory | None:
        row = await self._fetchone(
            "SELECT * FROM job_categories WHERE code = %(c)s",
            {"c": code},
        )
        return self._to_model(JobCategory, row)

    async def upsert_category(
        self,
        *,
        code: str,
        name_en: str,
        name_ar: str,
        parent_code: str | None = None,
        esco_uri: str | None = None,
        onet_code: str | None = None,
    ) -> JobCategory:
        row = await self._fetchone(
            """
            INSERT INTO job_categories (code, parent_code, name_en, name_ar, esco_uri, onet_code)
            VALUES (%(c)s, %(p)s, %(en)s, %(ar)s, %(esco)s, %(onet)s)
            ON CONFLICT (code) DO UPDATE SET
                parent_code = EXCLUDED.parent_code,
                name_en     = EXCLUDED.name_en,
                name_ar     = EXCLUDED.name_ar,
                esco_uri    = EXCLUDED.esco_uri,
                onet_code   = EXCLUDED.onet_code
            RETURNING *;
            """,
            {
                "c": code,
                "p": parent_code,
                "en": name_en,
                "ar": name_ar,
                "esco": esco_uri,
                "onet": onet_code,
            },
        )
        assert row is not None
        return JobCategory.model_validate(row)
