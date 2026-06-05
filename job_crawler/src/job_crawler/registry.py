"""Central registry mapping a source slug → crawler class.

Every registered source is a real, runnable crawler. Sources that depend
on external constraints (residential proxies for LinkedIn/Indeed/Glassdoor,
a queue-token for Jadarat) ship the working code path and log clearly
when they can't reach data.

Retired sources:
  * `mihnati` — removed in 2026-06 after the upstream search/listing
    endpoint went dead. `Search.aspx` returns a 404 page (the site
    sniffed the URL through its Rozee.pk parent and dropped the SA
    layer) and every `/category/...` URL responds 500. Probing
    `https://www.mihnati.com/` produced HTTP 500 with empty bodies on
    every UA tried. With no surviving endpoint there's no parser to
    fix; keeping the registry slot only generated noise. If the brand
    revives, re-add a fresh crawler against the new shape.
"""

from __future__ import annotations

from collections.abc import Iterable

from .ats.ashby import AshbyCrawler
from .ats.greenhouse import GreenhouseCrawler
from .ats.lever import LeverCrawler
from .ats.personio import PersonioCrawler
from .ats.recruitee import RecruiteeCrawler
from .ats.smartrecruiters import SmartRecruitersCrawler
from .ats.successfactors import SuccessFactorsCrawler
from .ats.workable import WorkableCrawler
from .ats.workday import WorkdayCrawler
from .boards.bayt import BaytCrawler
from .boards.company_careers import CompanyCareersCrawler
from .boards.glassdoor import GlassdoorCrawler
from .boards.indeed import IndeedCrawler
from .boards.jadarat import JadaratCrawler
from .boards.linkedin import LinkedInCrawler
from .boards.naukrigulf import NaukrigulfCrawler
from .boards.tanqeeb import TanqeebCrawler
from .boards.wuzzuf import WuzzufCrawler
from .core.base import BaseCrawler

# slug → crawler class. Order kept stable for the CLI's --list output.
REGISTRY: dict[str, type[BaseCrawler]] = {
    # ATS family (public JSON / XML)
    "greenhouse": GreenhouseCrawler,
    "lever": LeverCrawler,
    "workday": WorkdayCrawler,
    "workable": WorkableCrawler,
    "smartrecruiters": SmartRecruitersCrawler,
    "successfactors": SuccessFactorsCrawler,
    "recruitee": RecruiteeCrawler,
    "personio": PersonioCrawler,
    "ashby": AshbyCrawler,
    # Regional + local boards
    "bayt": BaytCrawler,
    "naukrigulf": NaukrigulfCrawler,
    "wuzzuf": WuzzufCrawler,
    "tanqeeb": TanqeebCrawler,
    "jadarat": JadaratCrawler,
    # Company-owned careers pages — the long-tail SA employers that
    # don't show up in Bayt or any standard ATS. Playwright-driven.
    "company_careers": CompanyCareersCrawler,
    # Aggregators — implemented; expect ~0 yield without residential proxies
    # or a captured session cookie (see each crawler's docstring).
    "linkedin": LinkedInCrawler,
    "indeed": IndeedCrawler,
    "glassdoor": GlassdoorCrawler,
}

ALL_SLUGS: tuple[str, ...] = tuple(REGISTRY)


def implemented_slugs() -> tuple[str, ...]:
    """Every registered slug — kept for back-compat with the CLI."""
    return ALL_SLUGS


def get(slug: str) -> type[BaseCrawler]:
    if slug not in REGISTRY:
        raise KeyError(
            f"unknown source '{slug}'. Known: {', '.join(REGISTRY)}",
        )
    return REGISTRY[slug]


def resolve_slugs(arg: str) -> Iterable[str]:
    """Expand a CLI selector to actual slugs.

    Special values:
        'all'        — every registered crawler
        'ats'        — every ATS crawler
        'boards'     — every board crawler
        '<slug>'     — exactly that slug
        '<s1,s2>'    — comma-separated list
    """
    if arg in ("all", "all-stubs"):  # back-compat with old selector
        return ALL_SLUGS
    if arg == "ats":
        from .ats._base import ATSBoardCrawler

        return tuple(
            s for s, c in REGISTRY.items() if issubclass(c, ATSBoardCrawler)
        )
    if arg == "boards":
        from .boards._base import BoardCrawler

        return tuple(
            s for s, c in REGISTRY.items() if issubclass(c, BoardCrawler)
        )
    if "," in arg:
        return tuple(s.strip() for s in arg.split(",") if s.strip())
    return (arg,)
