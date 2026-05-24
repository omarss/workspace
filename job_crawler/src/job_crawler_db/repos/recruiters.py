"""Recruiters repo — individual posters discovered on aggregator boards."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..models import Recruiter
from .base import Repo


class RecruitersRepo(Repo):
    async def create(
        self,
        *,
        full_name: str | None = None,
        headline: str | None = None,
        linkedin_url: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        agency_company_id: UUID | None = None,
        notes: str | None = None,
    ) -> Recruiter:
        """Create a recruiter. Schema CHECK requires at least one of
        full_name / linkedin_url / email."""
        if not (full_name or linkedin_url or email):
            raise ValueError("Provide at least one of full_name / linkedin_url / email.")
        row = await self._fetchone(
            """
            INSERT INTO recruiters (full_name, headline, linkedin_url, email, phone,
                                    agency_company_id, notes)
            VALUES (%(fn)s, %(h)s, %(li)s, %(e)s, %(p)s, %(agency)s, %(notes)s)
            RETURNING *;
            """,
            {
                "fn": full_name,
                "h": headline,
                "li": linkedin_url,
                "e": email,
                "p": phone,
                "agency": agency_company_id,
                "notes": notes,
            },
        )
        assert row is not None
        return Recruiter.model_validate(row)

    async def get(self, recruiter_id: UUID) -> Recruiter | None:
        row = await self._fetchone(
            "SELECT * FROM recruiters WHERE id = %(id)s",
            {"id": recruiter_id},
        )
        return self._to_model(Recruiter, row)

    async def get_by_linkedin_url(self, url: str) -> Recruiter | None:
        row = await self._fetchone(
            "SELECT * FROM recruiters WHERE linkedin_url = %(u)s",
            {"u": url},
        )
        return self._to_model(Recruiter, row)

    async def find_by_name(
        self,
        query: str,
        *,
        limit: int = 10,
        min_similarity: float = 0.4,
    ) -> list[tuple[Recruiter, float]]:
        rows = await self._fetchall(
            """
            SELECT *, similarity(normalize_en(full_name), normalize_en(%(q)s)) AS sim
            FROM recruiters
            WHERE full_name IS NOT NULL
              AND normalize_en(full_name) %% normalize_en(%(q)s)
              AND similarity(normalize_en(full_name), normalize_en(%(q)s)) >= %(min_sim)s
            ORDER BY sim DESC
            LIMIT %(lim)s;
            """,
            {"q": query, "min_sim": min_similarity, "lim": limit},
        )
        return [
            (Recruiter.model_validate({k: v for k, v in r.items() if k != "sim"}), float(r["sim"]))
            for r in rows
        ]

    async def resolve(
        self,
        *,
        linkedin_url: str | None = None,
        full_name: str | None = None,
        email: str | None = None,
        **extras: Any,
    ) -> Recruiter:
        """Find an existing recruiter or create one. Prefers linkedin_url."""
        if linkedin_url:
            existing = await self.get_by_linkedin_url(linkedin_url)
            if existing:
                return existing
        if email:
            row = await self._fetchone(
                "SELECT * FROM recruiters WHERE email = %(e)s LIMIT 1",
                {"e": email},
            )
            if row:
                return Recruiter.model_validate(row)
        return await self.create(
            full_name=full_name,
            linkedin_url=linkedin_url,
            email=email,
            **extras,
        )

    async def verify(self, recruiter_id: UUID, *, by: str) -> Recruiter:
        row = await self._fetchone(
            """
            UPDATE recruiters
            SET is_verified = true, verified_at = now(), verified_by = %(by)s
            WHERE id = %(id)s
            RETURNING *;
            """,
            {"id": recruiter_id, "by": by},
        )
        if row is None:
            raise KeyError(f"Recruiter {recruiter_id} not found")
        return Recruiter.model_validate(row)
