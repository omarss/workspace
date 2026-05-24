"""Core dataclasses every crawler exchanges with the runner.

Three stages of a posting's life inside the pipeline:

  1. Listing       — discovered from a search result; minimal fields
                     (URL + maybe a posted_at hint). Cheap to produce in bulk.
  2. RawPosting    — what `fetch_detail()` returns: the full HTTP body (or
                     JSON) + the resolved URL + timing. Stored on the
                     `job_crawler_db.JobPosting.raw_payload` jsonb column
                     for later re-extraction.
  3. ParsedPosting — structured fields after parsing the raw body. Carries
                     per-field confidence so the health detector can spot a
                     crawler whose extraction has regressed.

`normalize()` turns a ParsedPosting into the `JobPostingUpsert` the DB lib
expects, plus the side-channels (apply_channels, raw_skills) we collected
along the way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from job_crawler_db import (
    ApplicationChannelKind,
    EmploymentType,
    ExperienceLevel,
    GenderPreference,
    SalaryPeriod,
    WorkArrangement,
)


@dataclass(frozen=True, slots=True)
class Listing:
    """Lightweight handle to a job-detail page, discovered during search."""

    source_job_external_id: str
    detail_url: str
    posted_at_hint: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawPosting:
    """The raw bytes of a fetched detail page (HTML or JSON)."""

    listing: Listing
    canonical_url: str
    payload: dict[str, Any]  # parsed JSON or {'html': '...'}
    fetched_at: datetime
    duration_ms: int
    http_status: int
    bytes: int


@dataclass(slots=True)
class ApplicationChannelRaw:
    """One application channel found in the parsed posting."""

    kind: ApplicationChannelKind
    value: str
    is_primary: bool = False
    raw_label: str | None = None


@dataclass(slots=True)
class RawSkillRaw:
    """One skill phrase found in the parsed posting."""

    raw_phrase: str
    skill_slug: str | None = None  # set when extractor binds to a known skill
    confidence: float = 1.0


@dataclass(slots=True)
class ParsedPosting:
    """Structured fields after parsing a RawPosting.

    Every field is independently nullable; we record per-field success via
    `parsed_fields` so the health detector can spot regressions.
    """

    source_job_external_id: str
    canonical_url: str
    title: str
    posted_at: datetime | None = None
    source_updated_at: datetime | None = None
    expires_at: datetime | None = None
    description: str | None = None
    description_html: str | None = None

    # Employer
    raw_company_name: str | None = None
    company_external_id: str | None = None  # source-side id (LinkedIn co id)
    company_profile_url: str | None = None

    # Recruiter
    raw_poster_name: str | None = None
    poster_linkedin_url: str | None = None

    # Hiring manager (when discoverable — rare)
    hiring_manager_name: str | None = None
    hiring_manager_linkedin_url: str | None = None

    # Classification
    employment_type: EmploymentType | None = None
    work_arrangement: WorkArrangement | None = None
    experience_level: ExperienceLevel | None = None
    min_experience_years: int | None = None

    # Location
    raw_location: str | None = None
    city_name_hint: str | None = None
    country_code: str = "sa"
    office_address: str | None = None
    hybrid_days_per_week: int | None = None
    remote_country_restriction: str | None = None

    # Restrictions (Saudi-specific)
    saudi_nationals_only: bool = False
    gender_preference: GenderPreference = GenderPreference.any

    # Compensation
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: SalaryPeriod | None = None

    # Side-channels
    application_channels: list[ApplicationChannelRaw] = field(default_factory=list)
    raw_skills: list[RawSkillRaw] = field(default_factory=list)

    # Per-field success log used by health.evaluate(). Populated by parse()
    # to record which OPTIONAL fields produced a value vs. which were missed.
    parsed_fields: set[str] = field(default_factory=set)
    missing_fields: set[str] = field(default_factory=set)

    # The raw payload — copied through so postings.upsert can store it.
    raw_payload: dict[str, Any] = field(default_factory=dict)
