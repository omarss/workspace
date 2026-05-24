"""Postings repo — per-source observations + snapshots + application channels.

The `upsert` method is the crawler's hot path: it should be the single
call per fetched URL and must be both idempotent (re-fetching the same
listing bumps fetch_count without duplicating) and snapshot-recording
(text changes leave a row in `posting_snapshots`).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from ..enums import ApplicationChannelKind, PostingStatus
from ..hashing import content_hash, url_hash
from ..models import (
    ApplicationChannel,
    JobPosting,
    JobPostingUpsert,
    PostingSkillRaw,
    PostingSnapshot,
)
from .base import Repo

# Columns we compare to decide whether a snapshot is warranted. Anything not
# in this list (e.g. raw_payload, fetch_count, timestamps) is allowed to
# change silently.
_TRACKED_FIELDS: tuple[str, ...] = (
    "title",
    "description",
    "raw_company_name",
    "raw_location",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "employment_type",
    "work_arrangement",
    "experience_level",
    "status",
    "expires_at",
)


class PostingsRepo(Repo):
    # -- the hot path: upsert ------------------------------------------

    async def upsert(self, posting: JobPostingUpsert) -> JobPosting:
        """Insert or update a posting; record a snapshot when text changes.

        Idempotent on (source_id, source_job_external_id). On conflict:
          - fetch_count += 1
          - last_fetch_at + last_seen_at refreshed
          - any tracked field that differs is written through
          - a posting_snapshots row records the diff
        """
        url_h = url_hash(posting.canonical_url)
        content_h = content_hash(posting.description)
        raw_payload_json = _json(posting.raw_payload)

        # Run insert + snapshot inside one transaction so a snapshot is never
        # written without its parent's update committing. The pool sets the
        # connection-default row factory to `dict_row` (so SELECTs return
        # mappings); cursors below use that.
        async with self._pool.connection() as conn, conn.transaction():
            async with conn.cursor() as cur:
                # Try plain insert first; capture pre-existing row for diff.
                await cur.execute(
                    """
                        SELECT id, title, description, raw_company_name, raw_location,
                               salary_min, salary_max, salary_currency, salary_period,
                               employment_type, work_arrangement, experience_level,
                               status, expires_at, content_hash
                        FROM job_postings
                        WHERE source_id = %(sid)s AND source_job_external_id = %(eid)s;
                        """,
                    {"sid": posting.source_id, "eid": posting.source_job_external_id},
                )
                existing = await cur.fetchone()

                if existing is None:
                    await cur.execute(
                        _INSERT_SQL,
                        _insert_params(posting, url_h, content_h, raw_payload_json),
                    )
                    row = await cur.fetchone()
                    assert row is not None
                    return await self._select_by_id(conn, row["id"])

                posting_id = existing["id"]
                # Build the diff against tracked fields.
                changed = _diff(existing, posting, content_h)
                await cur.execute(
                    _UPDATE_SQL,
                    _update_params(posting_id, posting, url_h, content_h, raw_payload_json),
                )
                if changed:
                    await cur.execute(
                        """
                            INSERT INTO posting_snapshots
                              (posting_id, changed_fields, content_hash, status)
                            VALUES (%(pid)s, %(cf)s::jsonb, %(ch)s, %(st)s);
                            """,
                        {
                            "pid": posting_id,
                            "cf": json.dumps(changed, default=_jsonable),
                            "ch": content_h,
                            "st": posting.status.value,
                        },
                    )
                return await self._select_by_id(conn, posting_id)

    async def _select_by_id(
        self,
        conn: Any,
        posting_id: UUID,
    ) -> JobPosting:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM job_postings WHERE id = %(id)s",
                {"id": posting_id},
            )
            row = await cur.fetchone()
        assert row is not None
        return JobPosting.model_validate(row)

    # -- single-row fetches ---------------------------------------------

    async def get(self, posting_id: UUID) -> JobPosting | None:
        row = await self._fetchone(
            "SELECT * FROM job_postings WHERE id = %(id)s",
            {"id": posting_id},
        )
        return self._to_model(JobPosting, row)

    async def get_by_url(self, url: str) -> JobPosting | None:
        """Look up via the normalized URL hash (so query-param noise still finds it)."""
        row = await self._fetchone(
            "SELECT * FROM job_postings WHERE url_hash = %(h)s LIMIT 1",
            {"h": url_hash(url)},
        )
        return self._to_model(JobPosting, row)

    async def get_by_source(
        self,
        source_id: UUID,
        external_id: str,
    ) -> JobPosting | None:
        row = await self._fetchone(
            """
            SELECT * FROM job_postings
            WHERE source_id = %(s)s AND source_job_external_id = %(e)s;
            """,
            {"s": source_id, "e": external_id},
        )
        return self._to_model(JobPosting, row)

    # -- list / stream ---------------------------------------------------

    async def list_active(
        self,
        *,
        source_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JobPosting]:
        rows = await self._fetchall(
            """
            SELECT * FROM job_postings
            WHERE status = 'active'
              AND (%(sid)s::uuid IS NULL OR source_id = %(sid)s)
            ORDER BY last_seen_at DESC
            LIMIT %(lim)s OFFSET %(off)s;
            """,
            {"sid": source_id, "lim": limit, "off": offset},
        )
        return self._to_models(JobPosting, rows)

    async def stream_unclustered(
        self,
        *,
        batch_size: int = 500,
    ) -> AsyncIterator[JobPosting]:
        """Yield active postings that haven't been assigned to a cluster yet.

        Used by the clustering job — server-side cursor so it scales to
        millions of rows without blowing memory.
        """
        async for row in self._stream(
            """
            SELECT * FROM job_postings
            WHERE cluster_job_id IS NULL AND status = 'active'
            ORDER BY first_seen_at;
            """,
            batch_size=batch_size,
        ):
            yield JobPosting.model_validate(row)

    # -- mutations -------------------------------------------------------

    async def mark_status(self, posting_id: UUID, status: PostingStatus) -> None:
        await self._execute(
            """
            UPDATE job_postings SET status = %(s)s, last_seen_at = %(ts)s
            WHERE id = %(id)s;
            """,
            {"id": posting_id, "s": status.value, "ts": datetime.now(UTC)},
        )

    async def attach_to_cluster(self, posting_id: UUID, job_id: UUID) -> None:
        """Link a posting to a cluster. Bumps cluster posting_count too.

        Idempotent: no-op when the posting is already in `job_id`.
        """
        async with self._pool.connection() as conn, conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                        UPDATE job_postings SET cluster_job_id = %(j)s
                        WHERE id = %(p)s
                          AND (cluster_job_id IS DISTINCT FROM %(j)s)
                        RETURNING 1;
                        """,
                    {"p": posting_id, "j": job_id},
                )
                if await cur.fetchone() is None:
                    return  # already attached
                await cur.execute(
                    """
                        UPDATE jobs SET posting_count = posting_count + 1,
                                        last_seen_at  = greatest(last_seen_at, now())
                        WHERE id = %(j)s;
                        """,
                    {"j": job_id},
                )

    async def detach_from_cluster(self, posting_id: UUID) -> None:
        async with self._pool.connection() as conn, conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                        UPDATE job_postings SET cluster_job_id = NULL
                        WHERE id = %(p)s
                          AND cluster_job_id IS NOT NULL
                        RETURNING cluster_job_id;
                        """,
                    {"p": posting_id},
                )
                detached = await cur.fetchone()
                if detached is None:
                    return
                await cur.execute(
                    """
                        UPDATE jobs SET posting_count = GREATEST(posting_count - 1, 0)
                        WHERE id = %(j)s;
                        """,
                    {"j": detached["cluster_job_id"]},
                )

    # -- snapshots -------------------------------------------------------

    async def list_snapshots(self, posting_id: UUID) -> list[PostingSnapshot]:
        rows = await self._fetchall(
            """
            SELECT * FROM posting_snapshots
            WHERE posting_id = %(p)s
            ORDER BY fetched_at DESC;
            """,
            {"p": posting_id},
        )
        return self._to_models(PostingSnapshot, rows)

    # -- raw skills (extractor output) ---------------------------------

    async def add_raw_skill(
        self,
        posting_id: UUID,
        raw_phrase: str,
        *,
        skill_id: UUID | None = None,
        confidence: Decimal | float = Decimal("1.000"),
        extractor_version: str = "v1",
    ) -> PostingSkillRaw:
        row = await self._fetchone(
            """
            INSERT INTO posting_skills_raw
              (posting_id, skill_id, raw_phrase, extractor_version, confidence)
            VALUES (%(p)s, %(s)s, %(r)s, %(v)s, %(c)s)
            ON CONFLICT (posting_id, raw_phrase, extractor_version) DO UPDATE SET
                skill_id   = COALESCE(EXCLUDED.skill_id, posting_skills_raw.skill_id),
                confidence = EXCLUDED.confidence
            RETURNING *;
            """,
            {
                "p": posting_id,
                "s": skill_id,
                "r": raw_phrase,
                "v": extractor_version,
                "c": Decimal(str(confidence)),
            },
        )
        assert row is not None
        return PostingSkillRaw.model_validate(row)

    async def list_raw_skills_unmatched(
        self,
        *,
        limit: int = 100,
    ) -> list[PostingSkillRaw]:
        """Phrases the extractor saw but couldn't bind to a canonical skill.
        Feeds the human-curated alias backlog."""
        rows = await self._fetchall(
            """
            SELECT * FROM posting_skills_raw
            WHERE skill_id IS NULL
            ORDER BY created_at DESC
            LIMIT %(lim)s;
            """,
            {"lim": limit},
        )
        return self._to_models(PostingSkillRaw, rows)

    # -- application channels -------------------------------------------

    async def add_application_channel(
        self,
        posting_id: UUID,
        *,
        kind: ApplicationChannelKind,
        value: str,
        is_primary: bool = False,
        raw_label: str | None = None,
    ) -> ApplicationChannel:
        row = await self._fetchone(
            """
            INSERT INTO application_channels
              (posting_id, kind, value, is_primary, raw_label)
            VALUES (%(p)s, %(k)s, %(v)s, %(prim)s, %(lbl)s)
            ON CONFLICT (posting_id, kind, value) DO UPDATE SET
                is_primary = EXCLUDED.is_primary OR application_channels.is_primary,
                raw_label  = COALESCE(EXCLUDED.raw_label, application_channels.raw_label)
            RETURNING *;
            """,
            {
                "p": posting_id,
                "k": kind.value,
                "v": value,
                "prim": is_primary,
                "lbl": raw_label,
            },
        )
        assert row is not None
        return ApplicationChannel.model_validate(row)

    async def list_application_channels(
        self,
        posting_id: UUID,
    ) -> list[ApplicationChannel]:
        rows = await self._fetchall(
            """
            SELECT * FROM application_channels
            WHERE posting_id = %(p)s
            ORDER BY is_primary DESC, created_at;
            """,
            {"p": posting_id},
        )
        return self._to_models(ApplicationChannel, rows)


# ---------------------------------------------------------------------------
# private SQL fragments / helpers (kept out of the class for readability)
# ---------------------------------------------------------------------------
_INSERT_SQL = """
INSERT INTO job_postings (
    source_id, source_job_external_id, canonical_url, url_hash,
    company_id, raw_company_name, posted_by_recruiter_id, raw_poster_name,
    title, description, description_html, content_hash,
    employment_type, work_arrangement, experience_level,
    raw_location, city_id, office_address,
    hybrid_days_per_week, remote_country_restriction, relocation_assistance,
    hiring_manager_name, hiring_manager_linkedin_url,
    saudi_nationals_only, gender_preference,
    salary_min, salary_max, salary_currency, salary_period,
    status, posted_at, source_updated_at, expires_at, raw_payload
)
VALUES (
    %(source_id)s, %(eid)s, %(url)s, %(url_hash)s,
    %(company_id)s, %(raw_company_name)s, %(recruiter_id)s, %(raw_poster_name)s,
    %(title)s, %(description)s, %(description_html)s, %(content_hash)s,
    %(employment_type)s, %(work_arrangement)s, %(experience_level)s,
    %(raw_location)s, %(city_id)s, %(office_address)s,
    %(hybrid_days)s, %(remote_restriction)s, %(reloc)s,
    %(hm_name)s, %(hm_li)s,
    %(saudi_only)s, %(gender_pref)s,
    %(salary_min)s, %(salary_max)s, %(salary_currency)s, %(salary_period)s,
    %(status)s, %(posted_at)s, %(source_updated_at)s, %(expires_at)s, %(raw_payload)s::jsonb
)
RETURNING id;
"""


_UPDATE_SQL = """
UPDATE job_postings SET
    canonical_url           = %(url)s,
    url_hash                = %(url_hash)s,
    company_id              = COALESCE(%(company_id)s, company_id),
    raw_company_name        = COALESCE(%(raw_company_name)s, raw_company_name),
    posted_by_recruiter_id  = COALESCE(%(recruiter_id)s, posted_by_recruiter_id),
    raw_poster_name         = COALESCE(%(raw_poster_name)s, raw_poster_name),
    title                   = %(title)s,
    description             = COALESCE(%(description)s, description),
    description_html        = COALESCE(%(description_html)s, description_html),
    content_hash            = COALESCE(%(content_hash)s, content_hash),
    employment_type         = COALESCE(%(employment_type)s, employment_type),
    work_arrangement        = COALESCE(%(work_arrangement)s, work_arrangement),
    experience_level        = COALESCE(%(experience_level)s, experience_level),
    raw_location            = COALESCE(%(raw_location)s, raw_location),
    city_id                 = COALESCE(%(city_id)s, city_id),
    office_address          = COALESCE(%(office_address)s, office_address),
    hybrid_days_per_week    = COALESCE(%(hybrid_days)s, hybrid_days_per_week),
    remote_country_restriction = COALESCE(%(remote_restriction)s, remote_country_restriction),
    relocation_assistance   = COALESCE(%(reloc)s, relocation_assistance),
    hiring_manager_name     = COALESCE(%(hm_name)s, hiring_manager_name),
    hiring_manager_linkedin_url = COALESCE(%(hm_li)s, hiring_manager_linkedin_url),
    saudi_nationals_only    = %(saudi_only)s,
    gender_preference       = %(gender_pref)s::gender_preference,
    salary_min              = COALESCE(%(salary_min)s, salary_min),
    salary_max              = COALESCE(%(salary_max)s, salary_max),
    salary_currency         = COALESCE(%(salary_currency)s, salary_currency),
    salary_period           = COALESCE(%(salary_period)s, salary_period),
    status                  = %(status)s,
    posted_at               = COALESCE(%(posted_at)s, posted_at),
    source_updated_at       = COALESCE(%(source_updated_at)s, source_updated_at),
    expires_at              = COALESCE(%(expires_at)s, expires_at),
    last_seen_at            = now(),
    last_fetch_at           = now(),
    fetch_count             = fetch_count + 1,
    raw_payload             = COALESCE(%(raw_payload)s::jsonb, raw_payload)
WHERE id = %(id)s;
"""


def _insert_params(
    posting: JobPostingUpsert,
    url_h: bytes,
    content_h: bytes | None,
    raw_payload_json: str,
) -> dict[str, Any]:
    return {
        "source_id": posting.source_id,
        "eid": posting.source_job_external_id,
        "url": posting.canonical_url,
        "url_hash": url_h,
        "company_id": posting.company_id,
        "raw_company_name": posting.raw_company_name,
        "recruiter_id": posting.posted_by_recruiter_id,
        "raw_poster_name": posting.raw_poster_name,
        "title": posting.title,
        "description": posting.description,
        "description_html": posting.description_html,
        "content_hash": content_h,
        "employment_type": _enum(posting.employment_type),
        "work_arrangement": _enum(posting.work_arrangement),
        "experience_level": _enum(posting.experience_level),
        "raw_location": posting.raw_location,
        "city_id": posting.city_id,
        "office_address": posting.office_address,
        "hybrid_days": posting.hybrid_days_per_week,
        "remote_restriction": posting.remote_country_restriction,
        "reloc": posting.relocation_assistance,
        "hm_name": posting.hiring_manager_name,
        "hm_li": posting.hiring_manager_linkedin_url,
        "saudi_only": posting.saudi_nationals_only,
        "gender_pref": posting.gender_preference.value,
        "salary_min": posting.salary_min,
        "salary_max": posting.salary_max,
        "salary_currency": posting.salary_currency,
        "salary_period": _enum(posting.salary_period),
        "status": posting.status.value,
        "posted_at": posting.posted_at,
        "source_updated_at": posting.source_updated_at,
        "expires_at": posting.expires_at,
        "raw_payload": raw_payload_json,
    }


def _update_params(
    posting_id: UUID,
    posting: JobPostingUpsert,
    url_h: bytes,
    content_h: bytes | None,
    raw_payload_json: str,
) -> dict[str, Any]:
    params = _insert_params(posting, url_h, content_h, raw_payload_json)
    params["id"] = posting_id
    return params


def _diff(
    existing: dict[str, Any],
    fresh: JobPostingUpsert,
    fresh_content_hash: bytes | None,
) -> dict[str, Any]:
    """Return a dict of {field: new_value} for every tracked field that
    changed. `existing` is a dict-row mapping from the SELECT above."""
    changed: dict[str, Any] = {}
    if fresh.title != existing["title"]:
        changed["title"] = fresh.title
    if fresh.description and fresh_content_hash != existing["content_hash"]:
        # Hash-equality as the "changed?" signal — avoids storing massive
        # diffs when only whitespace shifted.
        changed["description"] = "<changed>"
    if fresh.raw_company_name and fresh.raw_company_name != existing["raw_company_name"]:
        changed["raw_company_name"] = fresh.raw_company_name
    if fresh.raw_location and fresh.raw_location != existing["raw_location"]:
        changed["raw_location"] = fresh.raw_location
    if fresh.salary_min is not None and fresh.salary_min != existing["salary_min"]:
        changed["salary_min"] = float(fresh.salary_min)
    if fresh.salary_max is not None and fresh.salary_max != existing["salary_max"]:
        changed["salary_max"] = float(fresh.salary_max)
    if fresh.salary_currency and fresh.salary_currency != existing["salary_currency"]:
        changed["salary_currency"] = fresh.salary_currency
    if fresh.salary_period and fresh.salary_period.value != existing["salary_period"]:
        changed["salary_period"] = fresh.salary_period.value
    if fresh.employment_type and fresh.employment_type.value != existing["employment_type"]:
        changed["employment_type"] = fresh.employment_type.value
    if fresh.work_arrangement and fresh.work_arrangement.value != existing["work_arrangement"]:
        changed["work_arrangement"] = fresh.work_arrangement.value
    if fresh.experience_level and fresh.experience_level.value != existing["experience_level"]:
        changed["experience_level"] = fresh.experience_level.value
    if fresh.status.value != existing["status"]:
        changed["status"] = fresh.status.value
    if fresh.expires_at and fresh.expires_at != existing["expires_at"]:
        changed["expires_at"] = fresh.expires_at.isoformat()
    return changed


def _enum(value: Any) -> str | None:
    return value.value if value is not None else None


def _json(value: dict[str, Any] | None) -> str:
    """Serialise to a JSON string. Empty / None becomes '{}' (never NULL) so
    the NOT NULL `raw_payload` column doesn't trip on first-insert."""
    return json.dumps(value or {}, default=_jsonable, ensure_ascii=False)


def _jsonable(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, UUID):
        return str(o)
    raise TypeError(f"Not JSON serialisable: {type(o)!r}")
