"""Search repo — ranked job retrieval across English + Arabic.

This is the single most important read path in the library. It combines
five recall signals into one ranked result list:

  1. tsvector full-text on `search_en` (English stemming via english_unaccent)
  2. tsvector full-text on `search_ar` (Arabic normalized via normalize_ar)
  3. Trigram typo-tolerance on titles
  4. Synonym expansion (k8s → kubernetes → كوبرنيتيس)
  5. Source-trust + recency boost so legit recent postings outrank stale ones

The scorer is a simple weighted sum — easy to tune, easy to explain.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from ..enums import (
    ClusterVerdict,
    EmploymentType,
    ExperienceLevel,
    SynonymKind,
    WorkArrangement,
)
from ..models import Job, JobSearchHit
from .base import Repo

# Any Arabic Unicode block (basic + supplement + extended-A + presentation forms).
_ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


class SearchRepo(Repo):
    """Ranked job-cluster search across English + Arabic with typo tolerance
    and synonym expansion.

    The synonym expander is *injected* (not imported) so tests can stub it
    out; production wires the real `SynonymsRepo.expand` in `db.py`.
    """

    __slots__ = ("_expand",)

    def __init__(
        self,
        pool: Any,
        *,
        synonym_expander: Any,  # async callable: expand(term, kind, locale) -> [(term, locale, weight)]
    ) -> None:
        super().__init__(pool)
        self._expand = synonym_expander

    # -- public API ------------------------------------------------------

    async def find_jobs(
        self,
        query: str | None = None,
        *,
        # Locale of the user-typed query. 'auto' detects Arabic vs Latin chars.
        locale: str = "auto",
        # Filters
        city_id: UUID | None = None,
        region_code: str | None = None,
        company_id: UUID | None = None,
        employment_type: EmploymentType | None = None,
        work_arrangement: WorkArrangement | None = None,
        experience_level: ExperienceLevel | None = None,
        min_experience_years: int | None = None,
        max_experience_years: int | None = None,
        min_salary: Decimal | float | None = None,
        max_salary: Decimal | float | None = None,
        required_skill_ids: Sequence[UUID] | None = None,
        saudi_nationals_only: bool | None = None,
        verdicts: Sequence[ClusterVerdict] | None = None,
        # Paging
        limit: int = 25,
        offset: int = 0,
        # Tuning
        include_pending: bool = True,
        min_score: float = 0.01,
        expand_synonyms: bool = True,
    ) -> list[JobSearchHit]:
        """Search ranked job clusters.

        Empty `query` returns clusters filtered only by the structured
        filters, ranked by recency.

        Returns at most `limit` hits, each carrying its score + the matched
        terms (useful for hit-highlighting in the UI).
        """
        # 1. Detect language + expand the query via the synonym tables.
        terms_en, terms_ar = await self._build_terms(query, locale, expand_synonyms)

        # 2. Compile tsqueries + trigram patterns.
        ts_en = _tsquery_or(terms_en)
        ts_ar = _tsquery_or(terms_ar)
        trgm_patterns_en = terms_en
        trgm_patterns_ar = terms_ar

        # 3. Build the verdict filter.
        if verdicts is not None:
            verdict_values = [v.value for v in verdicts]
        elif include_pending:
            verdict_values = [ClusterVerdict.legit.value, ClusterVerdict.pending.value]
        else:
            verdict_values = [ClusterVerdict.legit.value]

        # 4. Execute. The full SQL lives below; we pass NULLs through for
        #    sections that don't apply so the optimiser short-circuits them.
        rows = await self._fetchall(
            _SEARCH_SQL,
            {
                "ts_en": ts_en,
                "ts_ar": ts_ar,
                "trgm_en": trgm_patterns_en or [""],  # avoid empty-array casts
                "trgm_ar": trgm_patterns_ar or [""],
                "city_id": city_id,
                "region_code": region_code,
                "company_id": company_id,
                "employment_type": employment_type.value if employment_type else None,
                "work_arrangement": work_arrangement.value if work_arrangement else None,
                "experience_level": experience_level.value if experience_level else None,
                "min_exp": min_experience_years,
                "max_exp": max_experience_years,
                "min_sal": Decimal(str(min_salary)) if min_salary is not None else None,
                "max_sal": Decimal(str(max_salary)) if max_salary is not None else None,
                "skill_ids": list(required_skill_ids) if required_skill_ids else None,
                "saudi_only": saudi_nationals_only,
                "verdicts": verdict_values,
                "min_score": min_score,
                "lim": limit,
                "off": offset,
            },
        )

        hits: list[JobSearchHit] = []
        for row in rows:
            score = float(row.pop("rank_score"))
            matched_terms = list(row.pop("matched_terms", []) or [])
            matched_locale = row.pop("matched_locale", None)
            hits.append(
                JobSearchHit(
                    job=Job.model_validate(row),
                    score=score,
                    matched_terms=matched_terms,
                    matched_locale=matched_locale,
                )
            )
        return hits

    # -- helpers --------------------------------------------------------

    async def _build_terms(
        self,
        query: str | None,
        locale: str,
        expand: bool,
    ) -> tuple[list[str], list[str]]:
        """Split a query into English + Arabic forms, optionally expanded.

        Returns (english_terms, arabic_terms). Both lists may be empty.
        """
        if not query or not query.strip():
            return [], []

        detected = _detect_locale(query) if locale == "auto" else locale
        en: list[str] = []
        ar: list[str] = []

        # The original phrase always enters the matching set so an exact
        # text hit ranks above a synonym hit on a different concept.
        raw = query.strip()
        if detected == "ar":
            ar.append(raw)
        elif detected == "en":
            en.append(raw)
        else:  # 'mixed' or unknown
            en.append(raw)
            ar.append(raw)

        if not expand:
            return en, ar

        # Expand against general + skill + job_title groups. We try both kinds
        # because users mix free-text and skill names freely.
        for kind in (SynonymKind.general, SynonymKind.skill, SynonymKind.job_title):
            for term, term_locale, _weight in await self._expand(
                raw,
                kind=kind,
                locale=None,
            ):
                bucket = ar if (term_locale == "ar" or _has_arabic(term)) else en
                if term not in bucket:
                    bucket.append(term)
        return en, ar


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------
def _detect_locale(text: str) -> str:
    """Cheap heuristic: 'ar' if any Arabic char; 'en' otherwise."""
    return "ar" if _has_arabic(text) else "en"


def _has_arabic(text: str) -> bool:
    return bool(_ARABIC_RE.search(text or ""))


def _tsquery_or(terms: list[str]) -> str | None:
    """Build a websearch-safe OR query string. websearch_to_tsquery is
    forgiving of punctuation so we just OR raw terms with spaces and let
    Postgres parse."""
    cleaned = [t.strip() for t in terms if t and t.strip()]
    if not cleaned:
        return None
    # websearch_to_tsquery treats `OR` (uppercase, word) as union.
    return " OR ".join(f'"{t}"' if " " in t else t for t in cleaned)


# ---------------------------------------------------------------------------
# The big SQL
# ---------------------------------------------------------------------------
# The CTEs separate signal computation from ranking. Every signal is
# nullable; the WHERE clause keeps a row only if at least one matched.
_SEARCH_SQL = """
WITH
  -- normalised trigram patterns for typo tolerance
  trgm_en AS (
    SELECT unnest(%(trgm_en)s::text[]) AS pat
  ),
  trgm_ar AS (
    SELECT unnest(%(trgm_ar)s::text[]) AS pat
  ),
  ranked AS (
    SELECT
      j.*,
      -- Full-text scores
      CASE WHEN %(ts_en)s::text IS NOT NULL
           THEN ts_rank_cd(j.search_en, websearch_to_tsquery('english_unaccent', %(ts_en)s))
           ELSE 0 END AS rank_en,
      CASE WHEN %(ts_ar)s::text IS NOT NULL
           THEN ts_rank_cd(j.search_ar,
                           to_tsquery('simple',
                               regexp_replace(normalize_ar(%(ts_ar)s),
                                              '\\s+', ' | ', 'g')))
           ELSE 0 END AS rank_ar,
      -- Trigram bonus: max word_similarity across all trigram patterns.
      COALESCE((SELECT MAX(word_similarity(t.pat, normalize_en(j.title_en)))
                FROM trgm_en t WHERE t.pat <> ''), 0) AS wsim_en,
      COALESCE((SELECT MAX(word_similarity(normalize_ar(t.pat), normalize_ar(j.title_ar)))
                FROM trgm_ar t WHERE t.pat <> ''), 0) AS wsim_ar,
      -- Days since last seen (recency decay).
      EXTRACT(EPOCH FROM (now() - j.last_seen_at)) / 86400.0 AS age_days
    FROM jobs j
    WHERE j.deleted_at IS NULL
      AND j.verdict = ANY(%(verdicts)s::cluster_verdict[])
      AND (%(city_id)s::uuid IS NULL OR j.city_id = %(city_id)s)
      AND (%(region_code)s::text IS NULL OR j.region_code = %(region_code)s)
      AND (%(company_id)s::uuid IS NULL OR j.company_id = %(company_id)s)
      AND (%(employment_type)s::employment_type IS NULL
           OR j.employment_type = %(employment_type)s::employment_type)
      AND (%(work_arrangement)s::work_arrangement IS NULL
           OR j.work_arrangement = %(work_arrangement)s::work_arrangement)
      AND (%(experience_level)s::experience_level IS NULL
           OR j.experience_level = %(experience_level)s::experience_level)
      AND (%(min_exp)s::int IS NULL
           OR j.max_experience_years IS NULL
           OR j.max_experience_years >= %(min_exp)s)
      AND (%(max_exp)s::int IS NULL
           OR j.min_experience_years IS NULL
           OR j.min_experience_years <= %(max_exp)s)
      AND (%(min_sal)s::numeric IS NULL
           OR j.salary_max IS NULL OR j.salary_max >= %(min_sal)s)
      AND (%(max_sal)s::numeric IS NULL
           OR j.salary_min IS NULL OR j.salary_min <= %(max_sal)s)
      AND (%(saudi_only)s::boolean IS NULL
           OR j.saudi_nationals_only = %(saudi_only)s)
      AND (%(skill_ids)s::uuid[] IS NULL
           OR (
                SELECT COUNT(DISTINCT js.skill_id)
                FROM job_skills js
                WHERE js.job_id = j.id
                  AND js.skill_id = ANY(%(skill_ids)s::uuid[])
              ) = cardinality(%(skill_ids)s::uuid[]))
  ),
  scored AS (
    SELECT
      r.*,
      -- Weighted sum. Tweak weights here; they are intentionally exposed
      -- as plain numbers so any tuning experiment can A/B by changing one.
      (
        r.rank_en  * 0.35
      + r.rank_ar  * 0.35
      + r.wsim_en  * 0.10
      + r.wsim_ar  * 0.10
      + ln(GREATEST(r.posting_count, 1) + 1) * 0.05
      + GREATEST(0, 1.0 - r.age_days / 30.0) * 0.05
      ) AS rank_score,
      CASE
        WHEN r.rank_en > 0 AND r.rank_ar > 0 THEN NULL
        WHEN r.rank_en > 0 THEN 'en'
        WHEN r.rank_ar > 0 THEN 'ar'
        ELSE NULL
      END AS matched_locale,
      ARRAY(SELECT pat FROM trgm_en WHERE pat <> '' UNION
            SELECT pat FROM trgm_ar WHERE pat <> '') AS matched_terms
    FROM ranked r
  )
SELECT *
FROM scored
-- When no query is given we still want to surface jobs (filter-only mode),
-- so accept any row whose score is >= 0 by floor.
WHERE rank_score >= GREATEST(%(min_score)s::float, 0.0)
   OR (%(ts_en)s::text IS NULL AND %(ts_ar)s::text IS NULL)
ORDER BY
  rank_score DESC,
  last_seen_at DESC
LIMIT %(lim)s OFFSET %(off)s;
"""
