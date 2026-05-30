"""Unit tests for the Ashby parser.

The discovery / fetch path needs Playwright + Cloudflare access, which
is integration territory. These tests cover the JSON → ParsedPosting
mapping against a stable, hand-crafted payload.
"""

from __future__ import annotations

from datetime import UTC, datetime

from job_crawler.ats.ashby import AshbyCrawler, _employment, _iso_to_dt
from job_crawler.core.types import Listing, RawPosting
from job_crawler_db import EmploymentType, WorkArrangement


def _crawler() -> AshbyCrawler:
    """Build an AshbyCrawler shell suitable for parse-only tests.

    The base `BaseCrawler.__init__` requires an `http` client we don't
    need here, so we bypass __init__ entirely (the same pattern existing
    parser tests in `test_parsers.py` use for Greenhouse / Workable)."""
    c = AshbyCrawler.__new__(AshbyCrawler)
    c.http = None  # type: ignore[assignment]
    c.db = None
    return c


def _make_raw(
    job_overrides: dict[str, object] | None = None,
    board_slug: str = "linear",
) -> RawPosting:
    """Build a RawPosting wrapping a synthetic Ashby job payload."""
    base = {
        "id": "abc-123",
        "title": "Senior Backend Engineer",
        "locationName": "Riyadh, Saudi Arabia",
        "employmentType": "FullTime",
        "isListed": True,
        "isRemote": False,
        "publishedAt": "2026-05-21T14:30:00.000Z",
        "descriptionHtml": "<p>Build great software.</p>",
        "descriptionPlain": "Build great software.",
        "applicationFormUrl": "https://jobs.ashbyhq.com/linear/abc-123/application",
        "jobUrl": "https://jobs.ashbyhq.com/linear/abc-123",
    }
    if job_overrides:
        base.update(job_overrides)
    return RawPosting(
        listing=Listing(
            source_job_external_id="abc-123",
            detail_url="https://jobs.ashbyhq.com/linear/abc-123",
            extra={"board_slug": board_slug, "job_payload": base},
        ),
        canonical_url="https://jobs.ashbyhq.com/linear/abc-123",
        payload={"json": base, "board_slug": board_slug},
        fetched_at=datetime.now(UTC),
        duration_ms=0,
        http_status=200,
        bytes=len(str(base)),
    )


def test_parse_happy_path() -> None:
    parsed = _crawler().parse(_make_raw())
    assert parsed is not None
    assert parsed.title == "Senior Backend Engineer"
    assert parsed.source_job_external_id == "abc-123"
    assert parsed.raw_location == "Riyadh, Saudi Arabia"
    assert parsed.city_name_hint == "Riyadh"
    assert parsed.employment_type == EmploymentType.full_time
    assert parsed.posted_at == datetime(2026, 5, 21, 14, 30, tzinfo=UTC)
    assert parsed.description == "Build great software."
    assert parsed.description_html == "<p>Build great software.</p>"
    # Board slug used as fallback company name.
    assert parsed.raw_company_name == "Linear"
    assert parsed.company_external_id == "linear"
    # Apply channel = applicationFormUrl (the canonical "Apply" target).
    assert len(parsed.application_channels) == 1
    assert parsed.application_channels[0].is_primary
    assert parsed.application_channels[0].value == (
        "https://jobs.ashbyhq.com/linear/abc-123/application"
    )


def test_parse_returns_none_when_title_missing() -> None:
    assert _crawler().parse(_make_raw({"title": ""})) is None


def test_parse_returns_none_when_id_missing() -> None:
    assert _crawler().parse(_make_raw({"id": ""})) is None


def test_parse_remote_arrangement_from_isRemote_flag() -> None:
    parsed = _crawler().parse(
        _make_raw({"isRemote": True, "locationName": "Anywhere"})
    )
    assert parsed is not None
    assert parsed.work_arrangement == WorkArrangement.remote


def test_parse_hybrid_arrangement_from_location_text() -> None:
    parsed = _crawler().parse(
        _make_raw({"isRemote": False, "locationName": "Riyadh (Hybrid)"})
    )
    assert parsed is not None
    assert parsed.work_arrangement == WorkArrangement.hybrid


def test_parse_employment_type_camel_case_variants() -> None:
    for label, expected in [
        ("FullTime", EmploymentType.full_time),
        ("PartTime", EmploymentType.part_time),
        ("Contract", EmploymentType.contract),
        ("Intern", EmploymentType.internship),
        ("Internship", EmploymentType.internship),
        ("Temporary", EmploymentType.temporary),
    ]:
        assert _employment(label) is expected, label


def test_parse_employment_type_unknown_returns_none() -> None:
    assert _employment("WeirdNewLabel") is None
    assert _employment("") is None


def test_parse_falls_back_to_jobUrl_when_applicationFormUrl_missing() -> None:
    parsed = _crawler().parse(
        _make_raw({"applicationFormUrl": "", "jobUrl": "https://x.invalid/y"})
    )
    assert parsed is not None
    assert parsed.application_channels[0].value == "https://x.invalid/y"


def test_iso_to_dt_handles_z_suffix_and_naive() -> None:
    assert _iso_to_dt("2026-05-21T14:30:00.000Z") == datetime(
        2026, 5, 21, 14, 30, tzinfo=UTC,
    )
    assert _iso_to_dt(None) is None
    assert _iso_to_dt("") is None
    assert _iso_to_dt("not-a-date") is None
