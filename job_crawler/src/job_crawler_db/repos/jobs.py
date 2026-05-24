"""Jobs repo — clusters of postings + cluster-level skill links.

A cluster is "one real job". It is born when the dedupe pipeline links
the first posting to a new cluster row, and grows as more postings are
attached.  Its canonical text fields mirror the highest-trust posting in
the cluster (recomputed by `recompute_canonical`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from ..enums import (
    ClusterVerdict,
    EducationLevel,
    EmploymentType,
    ExperienceLevel,
    SalaryPeriod,
    SkillProficiency,
    SkillRequirement,
    WorkArrangement,
)
from ..models import Job, JobCreate, JobSkill, Skill
from .base import Repo


class JobsRepo(Repo):
    # -- create / fetch --------------------------------------------------

    async def create(self, payload: JobCreate) -> Job:
        """Insert a cluster row directly.

        Use sparingly — most clusters are born via `attach_first_posting()`
        which copies the posting's canonical fields automatically.
        """
        row = await self._fetchone(_INSERT_SQL, _params(payload))
        assert row is not None
        return Job.model_validate(row)

    async def create_from_posting(self, posting_id: UUID) -> Job:
        """Bootstrap a new cluster seeded from an existing posting's fields.

        Attaches the posting to the new cluster and marks it canonical.
        Idempotent: if the posting is already clustered, returns that cluster.
        """
        async with self._pool.connection() as conn, conn.transaction():
            from psycopg.rows import dict_row

            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT * FROM job_postings WHERE id = %(id)s FOR UPDATE",
                    {"id": posting_id},
                )
                posting = await cur.fetchone()
                if posting is None:
                    raise KeyError(f"Posting {posting_id} not found")
                if posting["cluster_job_id"]:
                    await cur.execute(
                        "SELECT * FROM jobs WHERE id = %(j)s",
                        {"j": posting["cluster_job_id"]},
                    )
                    row = await cur.fetchone()
                    assert row is not None
                    return Job.model_validate(row)

                # Route posting.title / description to the right bilingual
                # column based on the dominant script (Arabic → *_ar, else *_en).
                from ..text_utils import is_arabic_dominant

                title_ar = posting["title"] if is_arabic_dominant(posting["title"]) else None
                title_en = None if title_ar else posting["title"]
                desc_ar  = posting["description"] if is_arabic_dominant(posting["description"]) else None
                desc_en  = None if desc_ar else posting["description"]

                await cur.execute(
                    """
                        INSERT INTO jobs
                          (company_id, title_en, title_ar, description_en, description_ar,
                           employment_type, work_arrangement, experience_level,
                           city_id, country_code,
                           salary_min, salary_max, salary_currency, salary_period,
                           canonical_posting_id, posting_count,
                           first_seen_at, last_seen_at)
                        VALUES
                          (%(c)s, %(t_en)s, %(t_ar)s, %(d_en)s, %(d_ar)s,
                           %(emp)s, %(work)s, %(exp)s,
                           %(city)s, 'sa',
                           %(smin)s, %(smax)s, %(scur)s, %(sper)s,
                           %(pid)s, 1,
                           %(first)s, %(last)s)
                        RETURNING *;
                        """,
                    {
                        "c": posting["company_id"],
                        "t_en": title_en,
                        "t_ar": title_ar,
                        "d_en": desc_en,
                        "d_ar": desc_ar,
                        "emp": posting["employment_type"],
                        "work": posting["work_arrangement"],
                        "exp": posting["experience_level"],
                        "city": posting["city_id"],
                        "smin": posting["salary_min"],
                        "smax": posting["salary_max"],
                        "scur": posting["salary_currency"],
                        "sper": posting["salary_period"],
                        "pid": posting_id,
                        "first": posting["first_seen_at"],
                        "last": posting["last_seen_at"],
                    },
                )
                row = await cur.fetchone()
                assert row is not None
                await cur.execute(
                    "UPDATE job_postings SET cluster_job_id = %(j)s WHERE id = %(p)s",
                    {"j": row["id"], "p": posting_id},
                )
                return Job.model_validate(row)

    async def get(self, job_id: UUID) -> Job | None:
        row = await self._fetchone(
            "SELECT * FROM jobs WHERE id = %(id)s AND deleted_at IS NULL",
            {"id": job_id},
        )
        return self._to_model(Job, row)

    # -- updates ---------------------------------------------------------

    async def update(self, job_id: UUID, **fields: Any) -> Job:
        if not fields:
            job = await self.get(job_id)
            if job is None:
                raise KeyError(f"Job {job_id} not found")
            return job

        allowed = {
            "company_id",
            "title_en",
            "title_ar",
            "description_en",
            "description_ar",
            "category_code",
            "employment_type",
            "work_arrangement",
            "experience_level",
            "min_experience_years",
            "max_experience_years",
            "min_education_level",
            "preferred_fields_of_study",
            "city_id",
            "region_code",
            "country_code",
            "office_address",
            "office_latitude",
            "office_longitude",
            "hybrid_days_per_week",
            "remote_country_restriction",
            "relocation_assistance",
            "hiring_manager_name",
            "hiring_manager_linkedin_url",
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_period",
            "salary_is_negotiable",
            "saudi_nationals_only",
            "visa_sponsorship",
            "requires_arabic",
            "canonical_posting_id",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Unknown job fields: {sorted(bad)}")

        # Stringify enums; pass arrays / decimals as-is.
        for k, v in list(fields.items()):
            if hasattr(v, "value") and isinstance(getattr(v, "value", None), str):
                fields[k] = v.value
        sets = ", ".join(f"{k} = %({k})s" for k in fields)
        params: dict[str, Any] = dict(fields)
        params["id"] = job_id
        row = await self._fetchone(
            f"UPDATE jobs SET {sets} WHERE id = %(id)s RETURNING *;",
            params,
        )
        if row is None:
            raise KeyError(f"Job {job_id} not found")
        return Job.model_validate(row)

    async def set_verdict(
        self,
        job_id: UUID,
        verdict: ClusterVerdict,
        legit_score: Decimal | float | None = None,
    ) -> Job:
        row = await self._fetchone(
            """
            UPDATE jobs SET verdict = %(v)s,
                            legit_score = %(s)s
            WHERE id = %(id)s
            RETURNING *;
            """,
            {
                "id": job_id,
                "v": verdict.value,
                "s": Decimal(str(legit_score)) if legit_score is not None else None,
            },
        )
        if row is None:
            raise KeyError(f"Job {job_id} not found")
        return Job.model_validate(row)

    async def close(self, job_id: UUID) -> None:
        """Mark the cluster closed (all postings expired/removed)."""
        await self._execute(
            "UPDATE jobs SET closed_at = %(ts)s WHERE id = %(id)s AND closed_at IS NULL",
            {"id": job_id, "ts": datetime.now(UTC)},
        )

    async def soft_delete(self, job_id: UUID) -> None:
        await self._execute(
            "UPDATE jobs SET deleted_at = %(ts)s WHERE id = %(id)s",
            {"id": job_id, "ts": datetime.now(UTC)},
        )

    # -- canonical refresh ----------------------------------------------

    async def recompute_canonical(self, job_id: UUID) -> Job:
        """Re-pick the canonical posting (highest source trust * recency).

        Mirrors that posting's title/description/etc. into the cluster row.
        Cheap to call after every cluster mutation.
        """
        async with self._pool.connection() as conn:
            async with conn.transaction():
                from psycopg.rows import dict_row

                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT p.*
                        FROM job_postings p
                        JOIN sources s ON s.id = p.source_id
                        WHERE p.cluster_job_id = %(j)s
                          AND p.status = 'active'
                        ORDER BY s.trust_weight DESC, p.last_seen_at DESC
                        LIMIT 1;
                        """,
                        {"j": job_id},
                    )
                    chosen = await cur.fetchone()
                    if chosen is None:
                        # No active posting left — close the cluster if it
                        # still exists. If the row itself is gone (e.g. the
                        # caller already deleted it as part of a merge chain),
                        # raise KeyError so the caller can decide what to do.
                        await cur.execute(
                            """
                            UPDATE jobs
                            SET closed_at = COALESCE(closed_at, now())
                            WHERE id = %(j)s RETURNING *;
                            """,
                            {"j": job_id},
                        )
                        row = await cur.fetchone()
                        if row is None:
                            raise KeyError(f"Job {job_id} no longer exists")
                        return Job.model_validate(row)

                    await cur.execute(
                        """
                        UPDATE jobs SET
                            canonical_posting_id = %(p)s,
                            title_en        = %(title)s,
                            description_en  = COALESCE(%(desc)s, description_en),
                            employment_type = COALESCE(%(emp)s, employment_type),
                            work_arrangement= COALESCE(%(work)s, work_arrangement),
                            experience_level= COALESCE(%(exp)s, experience_level),
                            city_id         = COALESCE(%(city)s, city_id),
                            office_address  = COALESCE(%(office)s, office_address),
                            hybrid_days_per_week = COALESCE(%(hdays)s, hybrid_days_per_week),
                            remote_country_restriction = COALESCE(%(remote)s, remote_country_restriction),
                            relocation_assistance = COALESCE(%(reloc)s, relocation_assistance),
                            hiring_manager_name = COALESCE(%(hmname)s, hiring_manager_name),
                            hiring_manager_linkedin_url = COALESCE(%(hmli)s, hiring_manager_linkedin_url),
                            saudi_nationals_only = COALESCE(%(saudi_only)s, saudi_nationals_only),
                            gender_preference = COALESCE(%(gender_pref)s::gender_preference, gender_preference),
                            salary_min      = COALESCE(%(smin)s, salary_min),
                            salary_max      = COALESCE(%(smax)s, salary_max),
                            salary_currency = COALESCE(%(scur)s, salary_currency),
                            salary_period   = COALESCE(%(sper)s, salary_period),
                            last_seen_at    = greatest(last_seen_at, now())
                        WHERE id = %(j)s
                        RETURNING *;
                        """,
                        {
                            "j": job_id,
                            "p": chosen["id"],
                            "title": chosen["title"],
                            "desc": chosen["description"],
                            "emp": chosen["employment_type"],
                            "work": chosen["work_arrangement"],
                            "exp": chosen["experience_level"],
                            "city": chosen["city_id"],
                            "office": chosen["office_address"],
                            "hdays": chosen["hybrid_days_per_week"],
                            "remote": chosen["remote_country_restriction"],
                            "reloc": chosen["relocation_assistance"],
                            "hmname": chosen["hiring_manager_name"],
                            "hmli": chosen["hiring_manager_linkedin_url"],
                            "saudi_only": chosen["saudi_nationals_only"],
                            "gender_pref": chosen["gender_preference"],
                            "smin": chosen["salary_min"],
                            "smax": chosen["salary_max"],
                            "scur": chosen["salary_currency"],
                            "sper": chosen["salary_period"],
                        },
                    )
                    row = await cur.fetchone()
                    assert row is not None
                    return Job.model_validate(row)

    # -- cluster merge --------------------------------------------------

    async def merge(self, *, target: UUID, source: UUID) -> Job:
        """Move every posting from `source` into `target`, then delete source.

        Used when the dedupe job confirms two clusters represent the same
        real job. The losing cluster is hard-deleted (its evidence rows
        cascade); fake-signal evidence is preserved by re-pointing at target.
        """
        if target == source:
            raise ValueError("Cannot merge a cluster into itself")
        async with self._pool.connection() as conn, conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE job_postings SET cluster_job_id = %(t)s WHERE cluster_job_id = %(s)s",
                    {"t": target, "s": source},
                )
                moved = cur.rowcount
                await cur.execute(
                    "UPDATE job_fake_signals SET job_id = %(t)s WHERE job_id = %(s)s",
                    {"t": target, "s": source},
                )
                await cur.execute(
                    """
                        UPDATE jobs SET posting_count = posting_count + %(n)s,
                                        last_seen_at  = now()
                        WHERE id = %(t)s;
                        """,
                    {"t": target, "n": moved},
                )
                await cur.execute("DELETE FROM jobs WHERE id = %(s)s", {"s": source})
        return await self.recompute_canonical(target)

    # -- skill links ----------------------------------------------------

    async def link_skill(
        self,
        job_id: UUID,
        skill_id: UUID,
        *,
        requirement: SkillRequirement = SkillRequirement.required,
        proficiency_level: SkillProficiency | None = None,
        min_years: int | None = None,
        max_years: int | None = None,
        last_used_within_years: int | None = None,
        importance: Decimal | float = Decimal("0.500"),
        confidence: Decimal | float = Decimal("1.000"),
    ) -> JobSkill:
        row = await self._fetchone(
            """
            INSERT INTO job_skills
              (job_id, skill_id, requirement, proficiency_level,
               min_years, max_years, last_used_within_years,
               importance, confidence)
            VALUES (%(j)s, %(s)s, %(req)s, %(prof)s,
                    %(min_y)s, %(max_y)s, %(luw)s,
                    %(imp)s, %(conf)s)
            ON CONFLICT (job_id, skill_id) DO UPDATE SET
                requirement            = EXCLUDED.requirement,
                proficiency_level      = EXCLUDED.proficiency_level,
                min_years              = EXCLUDED.min_years,
                max_years              = EXCLUDED.max_years,
                last_used_within_years = EXCLUDED.last_used_within_years,
                importance             = EXCLUDED.importance,
                confidence             = EXCLUDED.confidence
            RETURNING *;
            """,
            {
                "j": job_id,
                "s": skill_id,
                "req": requirement.value,
                "prof": proficiency_level.value if proficiency_level else None,
                "min_y": min_years,
                "max_y": max_years,
                "luw": last_used_within_years,
                "imp": Decimal(str(importance)),
                "conf": Decimal(str(confidence)),
            },
        )
        assert row is not None
        return JobSkill.model_validate(row)

    async def list_skills(self, job_id: UUID) -> list[tuple[JobSkill, Skill]]:
        rows = await self._fetchall(
            """
            SELECT js.*, row_to_json(s.*) AS skill
            FROM job_skills js
            JOIN skills s ON s.id = js.skill_id
            WHERE js.job_id = %(j)s
            ORDER BY js.importance DESC, s.name_en;
            """,
            {"j": job_id},
        )
        out: list[tuple[JobSkill, Skill]] = []
        for row in rows:
            skill_dict = row.pop("skill")
            out.append(
                (JobSkill.model_validate(row), Skill.model_validate(skill_dict)),
            )
        return out

    async def unlink_skill(self, job_id: UUID, skill_id: UUID) -> None:
        await self._execute(
            "DELETE FROM job_skills WHERE job_id = %(j)s AND skill_id = %(s)s",
            {"j": job_id, "s": skill_id},
        )


# ---------------------------------------------------------------------------
# INSERT helper (cluster create — rare)
# ---------------------------------------------------------------------------
_INSERT_SQL = """
INSERT INTO jobs (
    company_id, title_en, title_ar, description_en, description_ar,
    category_code, employment_type, work_arrangement, experience_level,
    min_experience_years, max_experience_years,
    min_education_level, preferred_fields_of_study,
    city_id, region_code, country_code,
    office_address, office_latitude, office_longitude,
    hybrid_days_per_week, remote_country_restriction, relocation_assistance,
    hiring_manager_name, hiring_manager_linkedin_url,
    salary_min, salary_max, salary_currency, salary_period,
    salary_is_negotiable, saudi_nationals_only,
    visa_sponsorship, requires_arabic
)
VALUES (
    %(company_id)s, %(title_en)s, %(title_ar)s, %(description_en)s, %(description_ar)s,
    %(category_code)s, %(employment_type)s, %(work_arrangement)s, %(experience_level)s,
    %(min_experience_years)s, %(max_experience_years)s,
    %(min_education_level)s, %(preferred_fields_of_study)s,
    %(city_id)s, %(region_code)s, %(country_code)s,
    %(office_address)s, %(office_latitude)s, %(office_longitude)s,
    %(hybrid_days_per_week)s, %(remote_country_restriction)s, %(relocation_assistance)s,
    %(hiring_manager_name)s, %(hiring_manager_linkedin_url)s,
    %(salary_min)s, %(salary_max)s, %(salary_currency)s, %(salary_period)s,
    %(salary_is_negotiable)s, %(saudi_nationals_only)s,
    %(visa_sponsorship)s, %(requires_arabic)s
)
RETURNING *;
"""


def _params(p: JobCreate) -> dict[str, Any]:
    def _e(value: Any) -> str | None:
        return value.value if value is not None else None

    return {
        "company_id": p.company_id,
        "title_en": p.title_en,
        "title_ar": p.title_ar,
        "description_en": p.description_en,
        "description_ar": p.description_ar,
        "category_code": p.category_code,
        "employment_type": _e(p.employment_type),
        "work_arrangement": _e(p.work_arrangement),
        "experience_level": _e(p.experience_level),
        "min_experience_years": p.min_experience_years,
        "max_experience_years": p.max_experience_years,
        "min_education_level": _e(p.min_education_level),
        "preferred_fields_of_study": p.preferred_fields_of_study,
        "city_id": p.city_id,
        "region_code": p.region_code,
        "country_code": p.country_code,
        "office_address": p.office_address,
        "office_latitude": p.office_latitude,
        "office_longitude": p.office_longitude,
        "hybrid_days_per_week": p.hybrid_days_per_week,
        "remote_country_restriction": p.remote_country_restriction,
        "relocation_assistance": p.relocation_assistance,
        "hiring_manager_name": p.hiring_manager_name,
        "hiring_manager_linkedin_url": p.hiring_manager_linkedin_url,
        "salary_min": p.salary_min,
        "salary_max": p.salary_max,
        "salary_currency": p.salary_currency,
        "salary_period": _e(p.salary_period),
        "salary_is_negotiable": p.salary_is_negotiable,
        "saudi_nationals_only": p.saudi_nationals_only,
        "visa_sponsorship": p.visa_sponsorship,
        "requires_arabic": p.requires_arabic,
    }


# silence "json imported but unused" — keep it for future debug serialization
_ = json
_ = EmploymentType
_ = WorkArrangement
_ = ExperienceLevel
_ = SalaryPeriod
_ = EducationLevel
