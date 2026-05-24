"""Typed DTOs for every entity in the schema.

Conventions
-----------
* One pydantic `BaseModel` per table, named after the singular entity.
* `extra='ignore'` + `from_attributes=True` so the same model can be
  constructed from a psycopg `dict_row` mapping or a pydantic call.
* All fields are typed exactly per the SQL: `Decimal` for numeric, `UUID`
  for uuid, `datetime` for timestamptz, `bytes` for bytea, `dict` for jsonb.
* Create-input models live next to their read counterparts and contain
  only the fields a caller may set. The repo methods convert them into
  SQL parameter dicts.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    ApplicationChannelKind,
    ClusterVerdict,
    CrawlRunStatus,
    DuplicateReason,
    EducationLevel,
    EmploymentType,
    ExperienceLevel,
    FakeSignalKind,
    GenderPreference,
    PostingStatus,
    SalaryPeriod,
    SkillKind,
    SkillProficiency,
    SkillRequirement,
    SourceKind,
    SynonymKind,
    SynonymRelation,
    WorkArrangement,
)


# ---------------------------------------------------------------------------
# Base model with shared config
# ---------------------------------------------------------------------------
class _Base(BaseModel):
    """All entity models inherit from this — single place to tweak config."""

    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        # Plenty of columns are nullable; this keeps None-vs-missing semantics clean.
        validate_assignment=False,
        # Allow population from either alias or field name; not used yet but cheap.
        populate_by_name=True,
        # Frozen models are slightly faster and document immutability after read.
        frozen=False,
    )


# ---------------------------------------------------------------------------
# Reference / geo
# ---------------------------------------------------------------------------
class Country(_Base):
    code: str
    name_en: str
    name_ar: str
    dial_code: str
    currency: str


class SaRegion(_Base):
    code: str
    name_en: str
    name_ar: str
    country_code: str = "sa"


class SaCity(_Base):
    id: UUID
    region_code: str
    name_en: str
    name_ar: str
    latitude: Decimal | None = None
    longitude: Decimal | None = None


class Industry(_Base):
    code: str
    name_en: str
    name_ar: str
    isic_code: str | None = None


class JobCategory(_Base):
    code: str
    parent_code: str | None = None
    name_en: str
    name_ar: str
    esco_uri: str | None = None
    onet_code: str | None = None


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
class Source(_Base):
    id: UUID
    slug: str
    display_name: str
    kind: SourceKind
    base_url: str
    trust_weight: Decimal
    crawl_enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------
class Company(_Base):
    id: UUID
    name_en: str | None = None
    name_ar: str | None = None
    legal_name_en: str | None = None
    legal_name_ar: str | None = None
    cr_number: str | None = None
    website: str | None = None
    linkedin_url: str | None = None
    logo_url: str | None = None
    industry_code: str | None = None
    headquarters_city_id: UUID | None = None
    country_code: str = "sa"
    employee_count: int | None = None
    founded_year: int | None = None
    is_verified: bool = False
    verified_at: datetime | None = None
    verified_by: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class CompanyAlias(_Base):
    id: UUID
    company_id: UUID
    alias: str
    locale: str | None = None
    source_id: UUID | None = None
    created_at: datetime


class CompanySourceProfile(_Base):
    id: UUID
    company_id: UUID
    source_id: UUID
    source_company_external_id: str | None = None
    profile_url: str
    last_seen_at: datetime


# ---------------------------------------------------------------------------
# Recruiters
# ---------------------------------------------------------------------------
class Recruiter(_Base):
    id: UUID
    full_name: str | None = None
    headline: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    phone: str | None = None
    agency_company_id: UUID | None = None
    is_verified: bool = False
    verified_at: datetime | None = None
    verified_by: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------
class Skill(_Base):
    id: UUID
    slug: str
    name_en: str
    name_ar: str | None = None
    kind: SkillKind
    description: str | None = None
    esco_uri: str | None = None
    onet_code: str | None = None
    parent_id: UUID | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class SkillAlias(_Base):
    id: UUID
    skill_id: UUID
    alias: str
    locale: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Synonyms
# ---------------------------------------------------------------------------
class SynonymGroup(_Base):
    id: UUID
    canonical_term: str
    canonical_locale: str | None = None
    kind: SynonymKind = SynonymKind.general
    notes: str | None = None
    skill_id: UUID | None = None
    company_id: UUID | None = None
    category_code: str | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class SynonymTerm(_Base):
    id: UUID
    group_id: UUID
    term: str
    locale: str | None = None
    relation: SynonymRelation = SynonymRelation.synonym
    weight: Decimal = Decimal("1.000")
    created_at: datetime


# ---------------------------------------------------------------------------
# Jobs (cluster)
# ---------------------------------------------------------------------------
class Job(_Base):
    """Cluster of postings believed to represent one real job."""

    id: UUID
    company_id: UUID | None = None
    title_en: str | None = None
    title_ar: str | None = None
    description_en: str | None = None
    description_ar: str | None = None
    category_code: str | None = None
    employment_type: EmploymentType | None = None
    work_arrangement: WorkArrangement | None = None
    experience_level: ExperienceLevel | None = None
    min_experience_years: int | None = None
    max_experience_years: int | None = None
    min_education_level: EducationLevel | None = None
    preferred_fields_of_study: list[str] = Field(default_factory=list)
    # Primary location — additional offices live in job_locations.
    city_id: UUID | None = None
    region_code: str | None = None
    country_code: str = "sa"
    office_address: str | None = None
    office_latitude: Decimal | None = None
    office_longitude: Decimal | None = None
    hybrid_days_per_week: int | None = None
    remote_country_restriction: str | None = None
    relocation_assistance: bool | None = None
    # Hiring manager (the team lead doing the actual hiring).
    hiring_manager_name: str | None = None
    hiring_manager_linkedin_url: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = "SAR"
    salary_period: SalaryPeriod | None = None
    salary_is_negotiable: bool = False
    saudi_nationals_only: bool = False
    gender_preference: GenderPreference = GenderPreference.any
    visa_sponsorship: bool | None = None
    requires_arabic: bool | None = None
    verdict: ClusterVerdict = ClusterVerdict.pending
    legit_score: Decimal | None = None
    canonical_posting_id: UUID | None = None
    posting_count: int = 0
    first_seen_at: datetime
    last_seen_at: datetime
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class JobCreate(_Base):
    """Input for creating a cluster row directly (rare — usually created
    implicitly when the first posting is clustered)."""

    company_id: UUID | None = None
    title_en: str | None = None
    title_ar: str | None = None
    description_en: str | None = None
    description_ar: str | None = None
    category_code: str | None = None
    employment_type: EmploymentType | None = None
    work_arrangement: WorkArrangement | None = None
    experience_level: ExperienceLevel | None = None
    min_experience_years: int | None = None
    max_experience_years: int | None = None
    min_education_level: EducationLevel | None = None
    preferred_fields_of_study: list[str] = Field(default_factory=list)
    city_id: UUID | None = None
    region_code: str | None = None
    country_code: str = "sa"
    office_address: str | None = None
    office_latitude: Decimal | None = None
    office_longitude: Decimal | None = None
    hybrid_days_per_week: int | None = None
    remote_country_restriction: str | None = None
    relocation_assistance: bool | None = None
    hiring_manager_name: str | None = None
    hiring_manager_linkedin_url: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = "SAR"
    salary_period: SalaryPeriod | None = None
    salary_is_negotiable: bool = False
    saudi_nationals_only: bool = False
    gender_preference: GenderPreference = GenderPreference.any
    visa_sponsorship: bool | None = None
    requires_arabic: bool | None = None


class JobLocation(_Base):
    """Additional office for a cluster (multi-office jobs)."""

    id: UUID
    job_id: UUID
    city_id: UUID | None = None
    region_code: str | None = None
    country_code: str = "sa"
    office_address: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    is_primary: bool = False
    notes: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Postings (per-source observations)
# ---------------------------------------------------------------------------
class JobPosting(_Base):
    id: UUID
    source_id: UUID
    source_job_external_id: str
    canonical_url: str
    url_hash: bytes
    cluster_job_id: UUID | None = None
    company_id: UUID | None = None
    raw_company_name: str | None = None
    posted_by_recruiter_id: UUID | None = None
    raw_poster_name: str | None = None
    title: str
    description: str | None = None
    description_html: str | None = None
    content_hash: bytes | None = None
    employment_type: EmploymentType | None = None
    work_arrangement: WorkArrangement | None = None
    experience_level: ExperienceLevel | None = None
    raw_location: str | None = None
    city_id: UUID | None = None
    office_address: str | None = None
    hybrid_days_per_week: int | None = None
    remote_country_restriction: str | None = None
    relocation_assistance: bool | None = None
    hiring_manager_name: str | None = None
    hiring_manager_linkedin_url: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: SalaryPeriod | None = None
    status: PostingStatus = PostingStatus.active
    posted_at: datetime | None = None
    source_updated_at: datetime | None = None
    expires_at: datetime | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    last_fetch_at: datetime
    fetch_count: int = 1
    saudi_nationals_only: bool = False
    gender_preference: GenderPreference = GenderPreference.any
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class JobPostingUpsert(_Base):
    """Everything a crawler knows after a successful fetch.

    Used by `db.postings.upsert()` which dedupes on (source_id,
    source_job_external_id), bumps fetch_count + last_seen_at, and records
    a snapshot if any tracked field changed.
    """

    source_id: UUID
    source_job_external_id: str
    canonical_url: str
    title: str
    description: str | None = None
    description_html: str | None = None
    company_id: UUID | None = None
    raw_company_name: str | None = None
    posted_by_recruiter_id: UUID | None = None
    raw_poster_name: str | None = None
    employment_type: EmploymentType | None = None
    work_arrangement: WorkArrangement | None = None
    experience_level: ExperienceLevel | None = None
    raw_location: str | None = None
    city_id: UUID | None = None
    office_address: str | None = None
    hybrid_days_per_week: int | None = None
    remote_country_restriction: str | None = None
    relocation_assistance: bool | None = None
    hiring_manager_name: str | None = None
    hiring_manager_linkedin_url: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: SalaryPeriod | None = None
    status: PostingStatus = PostingStatus.active
    posted_at: datetime | None = None
    source_updated_at: datetime | None = None
    expires_at: datetime | None = None
    saudi_nationals_only: bool = False
    gender_preference: GenderPreference = GenderPreference.any
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class PostingSnapshot(_Base):
    id: UUID
    posting_id: UUID
    fetched_at: datetime
    changed_fields: dict[str, Any]
    content_hash: bytes | None = None
    status: PostingStatus


# ---------------------------------------------------------------------------
# Dedupe + fake-signal evidence
# ---------------------------------------------------------------------------
class DuplicateEdge(_Base):
    id: UUID
    posting_a_id: UUID
    posting_b_id: UUID
    reason: DuplicateReason
    similarity: Decimal
    detected_at: datetime
    detector_version: str


class FakeSignal(_Base):
    id: UUID
    job_id: UUID
    posting_id: UUID | None = None
    kind: FakeSignalKind
    weight: Decimal
    details: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime
    detector_version: str


# ---------------------------------------------------------------------------
# Application channels
# ---------------------------------------------------------------------------
class ApplicationChannel(_Base):
    id: UUID
    posting_id: UUID
    kind: ApplicationChannelKind
    value: str
    is_primary: bool = False
    raw_label: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Job-skill links
# ---------------------------------------------------------------------------
class JobSkill(_Base):
    job_id: UUID
    skill_id: UUID
    requirement: SkillRequirement = SkillRequirement.required
    proficiency_level: SkillProficiency | None = None
    min_years: int | None = None
    max_years: int | None = None
    last_used_within_years: int | None = None
    importance: Decimal = Decimal("0.500")
    confidence: Decimal = Decimal("1.000")
    created_at: datetime


class PostingSkillRaw(_Base):
    id: UUID
    posting_id: UUID
    skill_id: UUID | None = None
    raw_phrase: str
    extractor_version: str
    confidence: Decimal
    created_at: datetime


# ---------------------------------------------------------------------------
# Crawl operations
# ---------------------------------------------------------------------------
class CrawlRun(_Base):
    id: UUID
    source_id: UUID
    status: CrawlRunStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    pages_fetched: int = 0
    postings_seen: int = 0
    postings_new: int = 0
    error_count: int = 0
    config: dict[str, Any] = Field(default_factory=dict)
    error_summary: str | None = None


class CrawlFetch(_Base):
    id: UUID
    run_id: UUID
    source_id: UUID
    posting_id: UUID | None = None
    url: str
    http_status: int | None = None
    fetched_at: datetime
    duration_ms: int | None = None
    bytes: int | None = None
    outcome: str
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Search results
# ---------------------------------------------------------------------------
class JobSearchHit(_Base):
    """One ranked result from `db.search.find_jobs()`."""

    job: Job
    score: float
    matched_terms: list[str] = Field(default_factory=list)
    matched_locale: str | None = None  # 'en', 'ar', or None when both


__all__ = [
    "ApplicationChannel",
    "Company",
    "CompanyAlias",
    "CompanySourceProfile",
    "Country",
    "CrawlFetch",
    "CrawlRun",
    "DuplicateEdge",
    "FakeSignal",
    "Industry",
    "Job",
    "JobCategory",
    "JobCreate",
    "JobLocation",
    "JobPosting",
    "JobPostingUpsert",
    "JobSearchHit",
    "JobSkill",
    "PostingSkillRaw",
    "PostingSnapshot",
    "Recruiter",
    "SaCity",
    "SaRegion",
    "Skill",
    "SkillAlias",
    "Source",
    "SynonymGroup",
    "SynonymTerm",
]
