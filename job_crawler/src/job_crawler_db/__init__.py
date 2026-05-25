"""job_crawler_db — async PostgreSQL facade for the job_crawler schema.

Quick start
-----------
    import asyncio
    from job_crawler_db import JobCrawlerDB

    async def main() -> None:
        async with JobCrawlerDB.from_env() as db:
            source = await db.sources.upsert(
                slug="linkedin", display_name="LinkedIn",
                kind="aggregator", base_url="https://linkedin.com",
            )
            ...

    asyncio.run(main())

See README.md for the full API surface.
"""

from __future__ import annotations

from .ai_generation import AIDetectionResult, detect_ai_generation
from .db import JobCrawlerDB
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
from .hashing import content_hash, normalize_url, url_hash
from .models import (
    ApplicationChannel,
    City,
    Company,
    CompanyAlias,
    CompanySourceProfile,
    Country,
    CrawlFetch,
    CrawlRun,
    DuplicateEdge,
    FakeSignal,
    Industry,
    Job,
    JobCategory,
    JobCreate,
    JobLocation,
    JobPosting,
    JobPostingUpsert,
    JobSearchHit,
    JobSkill,
    PostingSkillRaw,
    PostingSnapshot,
    Recruiter,
    Region,
    Skill,
    SkillAlias,
    Source,
    SynonymGroup,
    SynonymTerm,
)
from .schema import apply_schema, schema_sql
from .settings import Settings

__version__ = "0.1.0"

__all__ = [
    "AIDetectionResult",
    "ApplicationChannel",
    "ApplicationChannelKind",
    "City",
    "ClusterVerdict",
    "Company",
    "CompanyAlias",
    "CompanySourceProfile",
    "Country",
    "CrawlFetch",
    "CrawlRun",
    "CrawlRunStatus",
    "DuplicateEdge",
    "DuplicateReason",
    "EducationLevel",
    "EmploymentType",
    "ExperienceLevel",
    "FakeSignal",
    "FakeSignalKind",
    "GenderPreference",
    "Industry",
    "Job",
    "JobCategory",
    "JobCrawlerDB",
    "JobCreate",
    "JobLocation",
    "JobPosting",
    "JobPostingUpsert",
    "JobSearchHit",
    "JobSkill",
    "PostingSkillRaw",
    "PostingSnapshot",
    "PostingStatus",
    "Recruiter",
    "Region",
    "SalaryPeriod",
    "Settings",
    "Skill",
    "SkillAlias",
    "SkillKind",
    "SkillProficiency",
    "SkillRequirement",
    "Source",
    "SourceKind",
    "SynonymGroup",
    "SynonymKind",
    "SynonymRelation",
    "SynonymTerm",
    "WorkArrangement",
    "__version__",
    "apply_schema",
    "content_hash",
    "detect_ai_generation",
    "normalize_url",
    "schema_sql",
    "url_hash",
]
