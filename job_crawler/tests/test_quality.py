"""Unit tests for `job_crawler.core.quality` — pure functions, no DB.

Covers every reason tag emitted by the three quality checkers so the
scorecard / counters interface stays stable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from job_crawler.core.quality import (
    QualityReject,
    check_intra_run_dup,
    check_listing,
    check_parsed,
)
from job_crawler.core.types import Listing, ParsedPosting

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _listing(url: str) -> Listing:
    return Listing(source_job_external_id="x", detail_url=url)


def _parsed(
    *,
    title: str = "Senior Python Engineer",
    description: str | None = (
        "We are hiring a backend engineer to build distributed services in Python. "
        "You will work on scaling our payments platform and lead reviews."
    ),
    raw_company_name: str | None = "Acme Saudi Arabia",
    posted_at: datetime | None = None,
) -> ParsedPosting:
    return ParsedPosting(
        source_job_external_id="xyz",
        canonical_url="https://example.invalid/job/xyz",
        title=title,
        description=description,
        raw_company_name=raw_company_name,
        posted_at=posted_at,
    )


# ---------------------------------------------------------------------------
# check_listing
# ---------------------------------------------------------------------------


def test_listing_accepts_real_detail_url() -> None:
    assert check_listing(_listing("https://boards.greenhouse.io/acme/jobs/42")) is None


@pytest.mark.parametrize(
    ("url", "expected_reason"),
    [
        ("", "bad_url"),
        ("not-a-url", "bad_url"),
        ("https://example.com/", "nav_url"),
        ("https://example.com", "nav_url"),
        ("https://example.com/search", "nav_url"),
        ("https://example.com/login", "nav_url"),
        ("https://example.com/jobs/search", "nav_url"),
        ("https://example.com/path/404", "nav_url"),
    ],
)
def test_listing_rejects_obvious_garbage(url: str, expected_reason: str) -> None:
    reject = check_listing(_listing(url))
    assert reject is not None
    assert reject.reason == expected_reason


def test_listing_keeps_unknown_slug_path() -> None:
    """A slug-only URL we've never seen before is NOT rejected — the
    listing gate is intentionally conservative to avoid false-positives
    on ATSes we don't know yet."""
    assert check_listing(_listing("https://careers.foo.com/positions/42")) is None
    assert check_listing(_listing("https://www.example.com/job/a-b-c")) is None


# ---------------------------------------------------------------------------
# check_parsed — title
# ---------------------------------------------------------------------------


def test_parsed_accepts_typical_posting() -> None:
    assert check_parsed(_parsed()) is None


def test_parsed_rejects_empty_title() -> None:
    reject = check_parsed(_parsed(title=""))
    assert reject is not None
    assert reject.reason == "empty_title"


def test_parsed_rejects_whitespace_only_title() -> None:
    reject = check_parsed(_parsed(title="   \n  "))
    assert reject is not None
    assert reject.reason == "empty_title"


def test_parsed_rejects_title_over_max_chars() -> None:
    long = "Senior Python Engineer " * 20  # ~440 chars
    reject = check_parsed(_parsed(title=long))
    assert reject is not None
    assert reject.reason == "long_title"


@pytest.mark.parametrize("placeholder", ["Job", "Jobs", "Apply", "n/a", "Untitled"])
def test_parsed_rejects_placeholder_titles(placeholder: str) -> None:
    reject = check_parsed(_parsed(title=placeholder))
    assert reject is not None
    assert reject.reason == "placeholder_title"


def test_parsed_rejects_non_alpha_title() -> None:
    reject = check_parsed(_parsed(title="12345 - 67890"))
    assert reject is not None
    assert reject.reason == "non_alpha_title"


# ---------------------------------------------------------------------------
# check_parsed — description
# ---------------------------------------------------------------------------


def test_parsed_rejects_short_description() -> None:
    reject = check_parsed(_parsed(description="Apply now"))
    assert reject is not None
    assert reject.reason == "short_description"


def test_parsed_rejects_none_description() -> None:
    reject = check_parsed(_parsed(description=None))
    assert reject is not None
    assert reject.reason == "short_description"


def test_parsed_rejects_low_diversity_description() -> None:
    """A description that's long but mostly repeats the same few words."""
    repetitive = "apply apply apply apply now now now now now now " * 30
    reject = check_parsed(_parsed(description=repetitive))
    assert reject is not None
    assert reject.reason == "low_diversity_description"


# ---------------------------------------------------------------------------
# check_parsed — company
# ---------------------------------------------------------------------------


def test_parsed_rejects_garbage_company_name() -> None:
    """Trailing-junk company name (caught by `_clean_company_name`)."""
    reject = check_parsed(_parsed(raw_company_name="Qwer0770&"))
    assert reject is not None
    assert reject.reason == "garbage_company"


def test_parsed_accepts_missing_company_name() -> None:
    """A posting WITHOUT a company name is still acceptable — some
    sources legitimately don't surface one. We only reject when the
    field is present-but-garbage."""
    assert check_parsed(_parsed(raw_company_name=None)) is None
    assert check_parsed(_parsed(raw_company_name="")) is None


# ---------------------------------------------------------------------------
# check_parsed — posted_at
# ---------------------------------------------------------------------------


def test_parsed_rejects_far_future_posted_at() -> None:
    now = datetime.now(UTC)
    future = now + timedelta(days=10)
    reject = check_parsed(_parsed(posted_at=future), now=now)
    assert reject is not None
    assert reject.reason == "future_posted_at"


def test_parsed_accepts_24h_future_posted_at() -> None:
    """JSON-LD timestamps can drift by a few hours due to timezone
    parsing slop. Don't reject these — only flag clearly-wrong dates."""
    now = datetime.now(UTC)
    near_future = now + timedelta(hours=12)
    assert check_parsed(_parsed(posted_at=near_future), now=now) is None


def test_parsed_rejects_stale_posted_at() -> None:
    now = datetime.now(UTC)
    very_old = now - timedelta(days=400)
    reject = check_parsed(_parsed(posted_at=very_old), now=now)
    assert reject is not None
    assert reject.reason == "stale_posted_at"


def test_parsed_accepts_missing_posted_at() -> None:
    """Sources without a posted_at hint are still valid postings."""
    assert check_parsed(_parsed(posted_at=None)) is None


def test_parsed_handles_tz_naive_posted_at() -> None:
    """Per-source parsers are inconsistent about tzinfo. The Bayt parser
    emits tz-naive `posted_at`; JSON-LD parsers emit tz-aware ones. Both
    must work without raising `TypeError: can't compare offset-naive and
    offset-aware datetimes`. Regression from the live v12 crawl where
    every Bayt posting aborted the run."""
    from datetime import datetime as dt
    now = datetime.now(UTC)
    naive_recent = dt(now.year, now.month, now.day)  # tz-naive
    # Should NOT raise; should return None (recent date passes both gates).
    assert check_parsed(_parsed(posted_at=naive_recent), now=now) is None

    # Tz-naive far-future date is still rejected (gate fires, comparison
    # works after the naive→UTC coercion).
    future_naive = (now + timedelta(days=10)).replace(tzinfo=None)
    reject = check_parsed(_parsed(posted_at=future_naive), now=now)
    assert reject is not None
    assert reject.reason == "future_posted_at"


# ---------------------------------------------------------------------------
# check_parsed — order of checks
# ---------------------------------------------------------------------------


def test_parsed_first_failed_check_wins() -> None:
    """When several gates would fire, the FIRST one is reported. This
    keeps scorecard counters deterministic across runs."""
    reject = check_parsed(
        _parsed(title="", description="short", raw_company_name="Bad@"),
    )
    assert reject is not None
    assert reject.reason == "empty_title"


# ---------------------------------------------------------------------------
# check_intra_run_dup
# ---------------------------------------------------------------------------


def test_intra_run_dup_allows_first_sighting() -> None:
    seen: set[bytes] = set()
    assert check_intra_run_dup(_parsed(), seen_content_hashes=seen) is None
    assert len(seen) == 1


def test_intra_run_dup_rejects_second_sighting() -> None:
    seen: set[bytes] = set()
    body = (
        "Identical description body that appears on two listings in the "
        "same run because the paginator surfaced page 1 and page 2 with "
        "overlapping items."
    )
    assert check_intra_run_dup(_parsed(description=body), seen_content_hashes=seen) is None
    second = check_intra_run_dup(_parsed(description=body), seen_content_hashes=seen)
    assert second is not None
    assert second.reason == "intra_run_dup"


def test_intra_run_dup_distinguishes_different_descriptions() -> None:
    seen: set[bytes] = set()
    assert check_intra_run_dup(_parsed(description="aaa aaa aaa"), seen_content_hashes=seen) is None
    assert check_intra_run_dup(_parsed(description="bbb bbb bbb"), seen_content_hashes=seen) is None
    assert len(seen) == 2


def test_intra_run_dup_skips_empty_description() -> None:
    """No description → no content_hash → can't dedup by it. Other
    gates (short_description) already reject the empty case."""
    seen: set[bytes] = set()
    assert check_intra_run_dup(_parsed(description=None), seen_content_hashes=seen) is None
    assert check_intra_run_dup(_parsed(description=""), seen_content_hashes=seen) is None
    assert seen == set()


# ---------------------------------------------------------------------------
# QualityReject shape
# ---------------------------------------------------------------------------


def test_quality_reject_is_frozen() -> None:
    """The dataclass is frozen so accidental mutation is caught by mypy
    and rejected at runtime."""
    r = QualityReject(reason="x", detail="y")
    with pytest.raises(Exception):
        r.reason = "z"  # type: ignore[misc]
