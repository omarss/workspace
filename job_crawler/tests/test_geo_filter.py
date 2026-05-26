"""Unit tests for `job_crawler.core.geo_filter`.

The function is the only GCC-vs-not-GCC gate the runner consults, so
mis-tuning it either spams the SA-focused corpus with global rows
(too permissive) or drops legitimate SA-only postings (too strict).
"""

from __future__ import annotations

import pytest

from job_crawler.core.geo_filter import is_gcc_location


@pytest.mark.parametrize(
    "raw_location",
    [
        "Riyadh, Saudi Arabia",
        "Jeddah",
        "Khobar",
        "Dubai, UAE",
        "Manama, Bahrain",
        "Kuwait City",
        "Doha, Qatar",
        "Muscat, Oman",
        "الرياض، المملكة العربية السعودية",
        "دبي",
    ],
)
def test_gcc_location_passes(raw_location: str) -> None:
    assert is_gcc_location(raw_location) is True


@pytest.mark.parametrize(
    "raw_location",
    [
        "Bangalore, India",
        "Bergen-Op-Zoom, Netherlands",
        "Pontirolo Nuovo, Italy",
        "Melbourne, Australia",
        "Eschborn, Germany",
        "London, United Kingdom",
        "San Francisco, USA",
        "Remote (Worldwide)",
    ],
)
def test_non_gcc_location_blocked(raw_location: str) -> None:
    assert is_gcc_location(raw_location) is False


def test_empty_raw_location_with_explicit_non_sa_country_uses_country() -> None:
    """A parser that extracts country_code='ae' from JSON-LD addressCountry
    without a city string should still pass the gate. The pre-fix code
    fell back to the country code; we preserve that path for explicitly
    non-'sa' codes (since the default is 'sa' so a non-default code
    means a parser deliberately set it)."""
    assert is_gcc_location(None, country_code="ae") is True
    assert is_gcc_location("", country_code="bh") is True


def test_empty_raw_location_with_non_gcc_country_blocked() -> None:
    """Cisco-style JSON-LD with addressCountry='US' + no raw_location
    should still get dropped."""
    assert is_gcc_location(None, country_code="us") is False
    assert is_gcc_location(None, country_code="in") is False


def test_empty_raw_location_with_default_sa_blocked() -> None:
    """The pre-fix behaviour was: empty raw_location + default
    country_code='sa' → pass. That let SABIC's Bangalore / Bergen-Op-Zoom
    roles through the gate. Post-fix: drop, because we can't tell
    whether 'sa' came from the parser or the dataclass default."""
    assert is_gcc_location(None, country_code="sa") is False
    assert is_gcc_location("", country_code="sa") is False


def test_empty_raw_location_with_no_country_blocked() -> None:
    assert is_gcc_location(None) is False
    assert is_gcc_location("") is False
    assert is_gcc_location(None, country_code=None) is False
