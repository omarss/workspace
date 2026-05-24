"""Companies repo — canonical employer entities + aliases + source profiles.

Resolution flow during crawling
-------------------------------
1. Crawler discovers a posting attributed to "Saudi Aramco" on LinkedIn.
2. Crawler calls `companies.resolve(raw_name="Saudi Aramco", source_id=…)`.
3. The repo searches:
     a. exact CR number (if known)
     b. exact LinkedIn URL match against `company_source_profiles`
     c. trigram match on `companies.name_en` / `name_ar`
     d. trigram match on `company_aliases.alias` (normalized)
4. If a confident match exists, return it; otherwise create a new company
   and register the raw name as a first alias.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ..models import Company, CompanyAlias, CompanySourceProfile
from .base import Repo


class CompaniesRepo(Repo):
    # -- create / fetch --------------------------------------------------

    async def create(
        self,
        *,
        name_en: str | None = None,
        name_ar: str | None = None,
        legal_name_en: str | None = None,
        legal_name_ar: str | None = None,
        cr_number: str | None = None,
        website: str | None = None,
        linkedin_url: str | None = None,
        logo_url: str | None = None,
        industry_code: str | None = None,
        headquarters_city_id: UUID | None = None,
        country_code: str = "sa",
        employee_count: int | None = None,
        founded_year: int | None = None,
        notes: str | None = None,
    ) -> Company:
        """Create a new company row.

        The schema CHECK enforces at least one of name_en / name_ar is non-null.
        """
        if not (name_en or name_ar):
            raise ValueError("At least one of name_en / name_ar is required.")
        row = await self._fetchone(
            """
            INSERT INTO companies
              (name_en, name_ar, legal_name_en, legal_name_ar, cr_number, website,
               linkedin_url, logo_url, industry_code, headquarters_city_id,
               country_code, employee_count, founded_year, notes)
            VALUES
              (%(name_en)s, %(name_ar)s, %(legal_en)s, %(legal_ar)s, %(cr)s,
               %(website)s, %(linkedin)s, %(logo)s, %(industry)s, %(hq_city)s,
               %(country)s, %(emp_count)s, %(founded)s, %(notes)s)
            RETURNING *;
            """,
            {
                "name_en": name_en,
                "name_ar": name_ar,
                "legal_en": legal_name_en,
                "legal_ar": legal_name_ar,
                "cr": cr_number,
                "website": website,
                "linkedin": linkedin_url,
                "logo": logo_url,
                "industry": industry_code,
                "hq_city": headquarters_city_id,
                "country": country_code,
                "emp_count": employee_count,
                "founded": founded_year,
                "notes": notes,
            },
        )
        assert row is not None
        return Company.model_validate(row)

    async def get(self, company_id: UUID) -> Company | None:
        row = await self._fetchone(
            "SELECT * FROM companies WHERE id = %(id)s AND deleted_at IS NULL",
            {"id": company_id},
        )
        return self._to_model(Company, row)

    async def get_by_cr_number(self, cr_number: str) -> Company | None:
        row = await self._fetchone(
            "SELECT * FROM companies WHERE cr_number = %(cr)s AND deleted_at IS NULL",
            {"cr": cr_number},
        )
        return self._to_model(Company, row)

    async def get_by_linkedin_url(self, url: str) -> Company | None:
        row = await self._fetchone(
            "SELECT * FROM companies WHERE linkedin_url = %(u)s AND deleted_at IS NULL",
            {"u": url},
        )
        return self._to_model(Company, row)

    # -- fuzzy lookup ---------------------------------------------------

    async def find_by_name(
        self,
        query: str,
        *,
        limit: int = 10,
        min_similarity: float = 0.4,
    ) -> list[tuple[Company, float]]:
        """Trigram-fuzzy search across name_en, name_ar, and every alias.

        Returns `(Company, similarity)` tuples sorted by best match first.
        Uses normalize_text() so the user can search Arabic-or-English,
        with or without diacritics, and find the right row.
        """
        rows = await self._fetchall(
            """
            WITH q AS (SELECT normalize_text(%(q)s) AS nq),
            candidates AS (
                SELECT c.id,
                       GREATEST(
                         COALESCE(similarity(normalize_en(c.name_en), q.nq), 0),
                         COALESCE(similarity(normalize_ar(c.name_ar), q.nq), 0),
                         COALESCE((
                             SELECT MAX(similarity(normalize_text(ca.alias), q.nq))
                             FROM company_aliases ca WHERE ca.company_id = c.id
                         ), 0)
                       ) AS sim
                FROM companies c, q
                WHERE c.deleted_at IS NULL
                  AND (
                      normalize_en(c.name_en) %% q.nq
                   OR normalize_ar(c.name_ar) %% q.nq
                   OR EXISTS (
                        SELECT 1 FROM company_aliases ca
                        WHERE ca.company_id = c.id
                          AND normalize_text(ca.alias) %% q.nq
                      )
                  )
            )
            SELECT c.*, cand.sim
            FROM candidates cand
            JOIN companies c ON c.id = cand.id
            WHERE cand.sim >= %(min_sim)s
            ORDER BY cand.sim DESC
            LIMIT %(lim)s;
            """,
            {"q": query, "min_sim": min_similarity, "lim": limit},
        )
        out: list[tuple[Company, float]] = []
        for row in rows:
            sim = float(row.pop("sim"))
            out.append((Company.model_validate(row), sim))
        return out

    # -- aliases + source profiles --------------------------------------

    async def add_alias(
        self,
        company_id: UUID,
        alias: str,
        *,
        locale: str | None = None,
        source_id: UUID | None = None,
    ) -> CompanyAlias:
        row = await self._fetchone(
            """
            INSERT INTO company_aliases (company_id, alias, locale, source_id)
            VALUES (%(cid)s, %(a)s, %(loc)s, %(sid)s)
            ON CONFLICT (company_id, alias) DO UPDATE SET
                locale = COALESCE(EXCLUDED.locale, company_aliases.locale)
            RETURNING *;
            """,
            {"cid": company_id, "a": alias, "loc": locale, "sid": source_id},
        )
        assert row is not None
        return CompanyAlias.model_validate(row)

    async def list_aliases(self, company_id: UUID) -> list[CompanyAlias]:
        rows = await self._fetchall(
            "SELECT * FROM company_aliases WHERE company_id = %(c)s ORDER BY created_at",
            {"c": company_id},
        )
        return self._to_models(CompanyAlias, rows)

    async def add_source_profile(
        self,
        company_id: UUID,
        source_id: UUID,
        profile_url: str,
        *,
        source_company_external_id: str | None = None,
    ) -> CompanySourceProfile:
        """Register a per-source profile URL (idempotent on (source_id, profile_url))."""
        row = await self._fetchone(
            """
            INSERT INTO company_source_profiles
              (company_id, source_id, source_company_external_id, profile_url, last_seen_at)
            VALUES (%(cid)s, %(sid)s, %(ext)s, %(url)s, now())
            ON CONFLICT (source_id, profile_url) DO UPDATE SET
                last_seen_at = now(),
                source_company_external_id = COALESCE(
                    EXCLUDED.source_company_external_id,
                    company_source_profiles.source_company_external_id
                )
            RETURNING *;
            """,
            {
                "cid": company_id,
                "sid": source_id,
                "ext": source_company_external_id,
                "url": profile_url,
            },
        )
        assert row is not None
        return CompanySourceProfile.model_validate(row)

    async def list_source_profiles(self, company_id: UUID) -> list[CompanySourceProfile]:
        rows = await self._fetchall(
            """
            SELECT * FROM company_source_profiles
            WHERE company_id = %(c)s
            ORDER BY last_seen_at DESC;
            """,
            {"c": company_id},
        )
        return self._to_models(CompanySourceProfile, rows)

    # -- write ops -------------------------------------------------------

    async def verify(self, company_id: UUID, *, by: str) -> Company:
        """Mark a company as human-verified (the official entity)."""
        row = await self._fetchone(
            """
            UPDATE companies
            SET is_verified = true, verified_at = now(), verified_by = %(by)s
            WHERE id = %(id)s
            RETURNING *;
            """,
            {"id": company_id, "by": by},
        )
        if row is None:
            raise KeyError(f"Company {company_id} not found")
        return Company.model_validate(row)

    async def update(self, company_id: UUID, **fields: Any) -> Company:
        """Partial update — only the keys you pass are written.

        Pass any subset of writable columns. Unknown keys raise ValueError to
        avoid silent typos (we explicitly allow only column names from the
        schema).
        """
        if not fields:
            company = await self.get(company_id)
            if company is None:
                raise KeyError(f"Company {company_id} not found")
            return company

        allowed = {
            "name_en",
            "name_ar",
            "legal_name_en",
            "legal_name_ar",
            "cr_number",
            "website",
            "linkedin_url",
            "logo_url",
            "industry_code",
            "headquarters_city_id",
            "country_code",
            "employee_count",
            "founded_year",
            "notes",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Unknown company fields: {sorted(bad)}")

        sets = ", ".join(f"{k} = %({k})s" for k in fields)
        params: dict[str, Any] = dict(fields)
        params["id"] = company_id
        row = await self._fetchone(
            f"UPDATE companies SET {sets} WHERE id = %(id)s RETURNING *;",
            params,
        )
        if row is None:
            raise KeyError(f"Company {company_id} not found")
        return Company.model_validate(row)

    async def soft_delete(self, company_id: UUID) -> None:
        await self._execute(
            "UPDATE companies SET deleted_at = %(ts)s WHERE id = %(id)s",
            {"id": company_id, "ts": datetime.now(UTC)},
        )

    # -- the high-level resolver ----------------------------------------

    async def resolve(
        self,
        *,
        raw_name: str | None = None,
        cr_number: str | None = None,
        linkedin_url: str | None = None,
        source_id: UUID | None = None,
        source_company_external_id: str | None = None,
        source_profile_url: str | None = None,
        min_similarity: float = 0.6,
    ) -> Company:
        """Find an existing company or create a new one from crawler input.

        Resolution order: CR number → LinkedIn URL → source profile URL →
        trigram match on name/aliases. Always records the raw name as an
        alias and the source profile URL when given.
        """
        if not (raw_name or cr_number or linkedin_url or source_profile_url):
            raise ValueError("Provide at least one identifying field.")

        # 1. Exact CR number — gold standard for SA companies.
        if cr_number:
            existing = await self.get_by_cr_number(cr_number)
            if existing:
                await self._maybe_register_alias_and_profile(
                    existing.id,
                    raw_name,
                    source_id,
                    source_profile_url,
                    source_company_external_id,
                )
                return existing

        # 2. Exact LinkedIn URL.
        if linkedin_url:
            existing = await self.get_by_linkedin_url(linkedin_url)
            if existing:
                await self._maybe_register_alias_and_profile(
                    existing.id,
                    raw_name,
                    source_id,
                    source_profile_url,
                    source_company_external_id,
                )
                return existing

        # 3. Exact source profile URL.
        if source_id and source_profile_url:
            row = await self._fetchone(
                """
                SELECT c.* FROM company_source_profiles p
                JOIN companies c ON c.id = p.company_id
                WHERE p.source_id = %(s)s AND p.profile_url = %(u)s
                  AND c.deleted_at IS NULL;
                """,
                {"s": source_id, "u": source_profile_url},
            )
            if row:
                existing = Company.model_validate(row)
                await self._maybe_register_alias_and_profile(
                    existing.id,
                    raw_name,
                    source_id,
                    source_profile_url,
                    source_company_external_id,
                )
                return existing

        # 4. Fuzzy by name + aliases.
        if raw_name:
            candidates = await self.find_by_name(raw_name, limit=1, min_similarity=min_similarity)
            if candidates:
                existing, _ = candidates[0]
                await self._maybe_register_alias_and_profile(
                    existing.id,
                    raw_name,
                    source_id,
                    source_profile_url,
                    source_company_external_id,
                )
                return existing

        # 5. Nothing matched — create.
        created = await self.create(
            name_en=raw_name,
            cr_number=cr_number,
            linkedin_url=linkedin_url,
        )
        await self._maybe_register_alias_and_profile(
            created.id,
            raw_name,
            source_id,
            source_profile_url,
            source_company_external_id,
        )
        return created

    async def _maybe_register_alias_and_profile(
        self,
        company_id: UUID,
        raw_name: str | None,
        source_id: UUID | None,
        profile_url: str | None,
        source_company_external_id: str | None,
    ) -> None:
        if raw_name:
            await self.add_alias(company_id, raw_name, source_id=source_id)
        if source_id and profile_url:
            await self.add_source_profile(
                company_id,
                source_id,
                profile_url,
                source_company_external_id=source_company_external_id,
            )
