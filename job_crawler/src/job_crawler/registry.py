"""Central registry mapping a source slug → crawler class.

Every planned source is listed here. Implemented sources point at a real
class; not-yet-implemented sources point at the `NotImplementedCrawler`
stub which raises a friendly error when the CLI tries to run them.

The CLI / Makefile both iterate `ALL_SLUGS` so adding a source is a
two-line drop-in: implement the class, swap the entry from STUB → class.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from job_crawler_db import SourceKind

from .ats.greenhouse import GreenhouseCrawler
from .ats.lever import LeverCrawler
from .ats.smartrecruiters import SmartRecruitersCrawler
from .ats.successfactors import SuccessFactorsCrawler
from .ats.workable import WorkableCrawler
from .ats.workday import WorkdayCrawler
from .boards.bayt import BaytCrawler
from .boards.linkedin import LinkedInCrawler
from .boards.naukrigulf import NaukrigulfCrawler
from .boards.wuzzuf import WuzzufCrawler
from .core.base import BaseCrawler
from .core.config import RateConfig


class NotImplementedCrawler(BaseCrawler):
    """Placeholder for sources we plan to support but haven't wired yet."""

    source_slug: ClassVar[str] = "stub"
    source_display_name: ClassVar[str] = "stub"
    source_kind: ClassVar[SourceKind] = SourceKind.aggregator
    source_base_url: ClassVar[str] = "https://example.invalid"
    rate: ClassVar[RateConfig] = RateConfig()

    async def discover_listings(self, *, since):  # type: ignore[override]
        raise NotImplementedError(
            f"crawler '{self.source_slug}' is on the roadmap but not implemented yet"
        )
        yield  # pragma: no cover — makes the function a generator

    def parse(self, raw):  # type: ignore[override]
        raise NotImplementedError

    def normalize(self, parsed):  # type: ignore[override]
        raise NotImplementedError


def _stub_for(slug: str, display: str, kind: SourceKind, base_url: str) -> type[BaseCrawler]:
    """Factory: build a NotImplementedCrawler subclass that identifies itself."""
    return type(
        f"{slug.replace('-', '_').title()}Stub",
        (NotImplementedCrawler,),
        {
            "source_slug": slug,
            "source_display_name": display,
            "source_kind": kind,
            "source_base_url": base_url,
        },
    )


# slug → crawler class. Order kept stable for the CLI's --list output.
REGISTRY: dict[str, type[BaseCrawler]] = {
    # ATS family (public JSON, easy)
    "greenhouse": GreenhouseCrawler,
    "lever": LeverCrawler,
    "workday": WorkdayCrawler,
    "workable": WorkableCrawler,
    "smartrecruiters": SmartRecruitersCrawler,
    "successfactors": SuccessFactorsCrawler,
    "recruitee": _stub_for("recruitee", "Recruitee", SourceKind.ats, "https://recruitee.com"),
    "personio": _stub_for("personio", "Personio", SourceKind.ats, "https://jobs.personio.com"),
    # Regional + local boards
    "bayt": BaytCrawler,
    "naukrigulf": NaukrigulfCrawler,
    "wuzzuf": WuzzufCrawler,
    "tanqeeb": _stub_for("tanqeeb", "Tanqeeb", SourceKind.local_board, "https://www.tanqeeb.com"),
    "mihnati": _stub_for("mihnati", "Mihnati", SourceKind.local_board, "https://www.mihnati.com"),
    "jadarat": _stub_for("jadarat", "Jadarat", SourceKind.gov_board, "https://jadarat.sa"),
    # Aggregators (bot-hostile — phase 3+)
    "linkedin": LinkedInCrawler,
    "indeed": _stub_for("indeed", "Indeed", SourceKind.aggregator, "https://sa.indeed.com"),
    # Glassdoor is in the same boat as LinkedIn.
    "glassdoor": _stub_for(
        "glassdoor", "Glassdoor", SourceKind.aggregator, "https://www.glassdoor.sa"
    ),
}

ALL_SLUGS: tuple[str, ...] = tuple(REGISTRY)


def implemented_slugs() -> tuple[str, ...]:
    """Subset of ALL_SLUGS whose crawler class is NOT a stub."""
    return tuple(
        slug for slug, cls in REGISTRY.items() if not issubclass(cls, NotImplementedCrawler)
    )


def get(slug: str) -> type[BaseCrawler]:
    if slug not in REGISTRY:
        raise KeyError(
            f"unknown source '{slug}'. Known: {', '.join(REGISTRY)}",
        )
    return REGISTRY[slug]


def resolve_slugs(arg: str) -> Iterable[str]:
    """Expand a CLI selector to actual slugs.

    Special values:
        'all'        — every implemented crawler
        'all-stubs'  — every registered slug, stubs included
        'ats'        — implemented ATS crawlers only
        'boards'     — implemented board crawlers only
        '<slug>'     — exactly that slug
        '<s1,s2>'    — comma-separated list
    """
    if arg == "all":
        return implemented_slugs()
    if arg == "all-stubs":
        return ALL_SLUGS
    if arg == "ats":
        from .ats._base import ATSBoardCrawler

        return tuple(
            s
            for s, c in REGISTRY.items()
            if issubclass(c, ATSBoardCrawler) and not issubclass(c, NotImplementedCrawler)
        )
    if arg == "boards":
        from .boards._base import BoardCrawler

        return tuple(
            s
            for s, c in REGISTRY.items()
            if issubclass(c, BoardCrawler) and not issubclass(c, NotImplementedCrawler)
        )
    if "," in arg:
        return tuple(s.strip() for s in arg.split(",") if s.strip())
    return (arg,)
