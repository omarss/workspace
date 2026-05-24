"""Python enums mirroring every CREATE TYPE in db_schema.sql.

Names and values match exactly so psycopg can adapt them to/from the
underlying Postgres enums without a custom type registration.
"""

from __future__ import annotations

from enum import StrEnum


class SourceKind(StrEnum):
    aggregator = "aggregator"
    regional_board = "regional_board"
    local_board = "local_board"
    gov_board = "gov_board"
    ats = "ats"
    company_site = "company_site"


class EmploymentType(StrEnum):
    full_time = "full_time"
    part_time = "part_time"
    contract = "contract"
    temporary = "temporary"
    internship = "internship"
    freelance = "freelance"
    volunteer = "volunteer"


class WorkArrangement(StrEnum):
    onsite = "onsite"
    hybrid = "hybrid"
    remote = "remote"


class ExperienceLevel(StrEnum):
    entry = "entry"
    junior = "junior"
    mid = "mid"
    senior = "senior"
    lead = "lead"
    manager = "manager"
    director = "director"
    executive = "executive"


class SalaryPeriod(StrEnum):
    hourly = "hourly"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    annual = "annual"
    project = "project"


class PostingStatus(StrEnum):
    active = "active"
    expired = "expired"
    removed = "removed"
    error = "error"


class ClusterVerdict(StrEnum):
    pending = "pending"
    legit = "legit"
    suspicious = "suspicious"
    fake = "fake"
    recycled = "recycled"


class SkillKind(StrEnum):
    hard = "hard"
    soft = "soft"
    language = "language"
    certification = "certification"
    tool = "tool"


class SkillRequirement(StrEnum):
    required = "required"
    preferred = "preferred"
    nice_to_have = "nice_to_have"


class DuplicateReason(StrEnum):
    exact_url = "exact_url"
    exact_content_hash = "exact_content_hash"
    near_content = "near_content"
    title_company_loc = "title_company_loc"
    cross_source_repost = "cross_source_repost"
    manual = "manual"


class FakeSignalKind(StrEnum):
    salary_outlier_high = "salary_outlier_high"
    salary_outlier_low = "salary_outlier_low"
    no_company_match = "no_company_match"
    newly_registered_company = "newly_registered_company"
    generic_description = "generic_description"
    requests_payment = "requests_payment"
    requests_personal_docs_early = "requests_personal_docs_early"
    broken_apply_link = "broken_apply_link"
    duplicate_across_unrelated_companies = "duplicate_across_unrelated_companies"
    mismatched_location_visa = "mismatched_location_visa"
    mass_posted_template = "mass_posted_template"
    reposted_within_30d = "reposted_within_30d"
    contact_via_personal_channel = "contact_via_personal_channel"
    ai_generated_description = "ai_generated_description"


class CrawlRunStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ApplicationChannelKind(StrEnum):
    url = "url"
    email = "email"
    whatsapp = "whatsapp"
    phone = "phone"
    in_app = "in_app"
    fax = "fax"


class SkillProficiency(StrEnum):
    basic = "basic"
    intermediate = "intermediate"
    advanced = "advanced"
    expert = "expert"
    native = "native"


class EducationLevel(StrEnum):
    none = "none"
    high_school = "high_school"
    diploma = "diploma"
    bachelor = "bachelor"
    master = "master"
    phd = "phd"


class SynonymKind(StrEnum):
    skill = "skill"
    job_title = "job_title"
    company = "company"
    location = "location"
    industry = "industry"
    general = "general"


class SynonymRelation(StrEnum):
    synonym = "synonym"
    abbreviation = "abbreviation"
    translation = "translation"
    broader = "broader"
    narrower = "narrower"


class GenderPreference(StrEnum):
    any = "any"
    male_only = "male_only"
    female_only = "female_only"
