"""ATS `boards()` warns when no boards are configured.

Several ATS sources ship with an empty `default_boards` and expect
runtime configuration via env or `discover --ats`. When neither is
present they complete silently with 0 fetches; the warning surfaces
the misconfiguration in journalctl without changing crawler behaviour.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import ClassVar

import pytest

from job_crawler.ats._base import ATSBoardCrawler
from job_crawler.core.types import Listing, ParsedPosting, RawPosting


class _FakeCrawler(ATSBoardCrawler):
    """Bare-bones ATS subclass used only to exercise `boards()`."""

    source_slug: ClassVar[str] = "fake_ats"
    source_display_name: ClassVar[str] = "Fake ATS"
    source_base_url: ClassVar[str] = "https://example.invalid"
    source_trust_weight: ClassVar[float] = 0.5
    boards_env_var: ClassVar[str] = "JC_FAKE_BOARDS"
    default_boards: ClassVar[tuple[str, ...]] = ()

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        # Required by BaseCrawler; never invoked from these tests.
        if False:  # pragma: no cover
            yield Listing(source_job_external_id="", detail_url="")

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        # Required by BaseCrawler; never invoked from these tests.
        return None


async def test_boards_warns_when_empty(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JC_FAKE_BOARDS", raising=False)
    crawler = _FakeCrawler.__new__(_FakeCrawler)
    crawler.db = None
    with caplog.at_level(logging.WARNING, logger="job_crawler.ats"):
        result = await crawler.boards()
    assert result == ()
    assert any(
        "no boards configured" in rec.message and "fake_ats" in rec.message
        for rec in caplog.records
    ), f"expected warning, got: {[r.message for r in caplog.records]}"


async def test_boards_does_not_warn_when_env_populated(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JC_FAKE_BOARDS", "acme,beta")
    crawler = _FakeCrawler.__new__(_FakeCrawler)
    crawler.db = None
    with caplog.at_level(logging.WARNING, logger="job_crawler.ats"):
        result = await crawler.boards()
    assert result == ("acme", "beta")
    assert not any(
        "no boards configured" in rec.message for rec in caplog.records
    )


async def test_boards_does_not_warn_when_default_populated(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JC_FAKE_BOARDS", raising=False)

    class _Seeded(_FakeCrawler):
        default_boards: ClassVar[tuple[str, ...]] = ("seeded-board",)

    crawler = _Seeded.__new__(_Seeded)
    crawler.db = None
    with caplog.at_level(logging.WARNING, logger="job_crawler.ats"):
        result = await crawler.boards()
    assert result == ("seeded-board",)
    assert not any(
        "no boards configured" in rec.message for rec in caplog.records
    )
