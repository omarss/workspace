"""Shared helpers for ATS-hosted crawlers.

All ATS crawlers iterate the boards of a configurable set of companies
in this precedence order:

  1. JC_*_BOARDS env var (manual override)
  2. company_source_profiles rows discovered by `discover --ats`
  3. The class's `default_boards` hard-coded seed

Use `await self.boards()` to get the merged list.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import ClassVar, Final

from ..core.base import BaseCrawler
from ..core.db_boards import db_boards_for, merge_board_lists

_LOG: Final = logging.getLogger("job_crawler.ats")


def env_board_slugs(env_var: str, fallback: Iterable[str] = ()) -> tuple[str, ...]:
    """Read a comma-separated list of board slugs from an env var.

    Example:
        JC_GREENHOUSE_BOARDS=stripe,gitlab,vercel make crawl-greenhouse
    """
    raw = os.environ.get(env_var, "").strip()
    if raw:
        return tuple(s.strip() for s in raw.split(",") if s.strip())
    return tuple(fallback)


class ATSBoardCrawler(BaseCrawler):
    """Marker base — every ATS crawler is one of these.

    ATS public APIs (Greenhouse, Lever, Workable, etc.) are explicitly
    designed for programmatic consumption, but their root robots.txt
    sometimes blocks all bots indiscriminately. We override
    `respect_robots = False` here; per-crawler subclasses can flip it
    back on if needed.
    """

    # All four are intentionally class-level — `ClassVar` keeps mypy
    # from treating subclass `ClassVar` redeclarations as overrides
    # of instance variables (Finding 2).
    respect_robots: ClassVar[bool] = False
    # ATS boards return jobs for *all* their tenants' locations. We only
    # care about GCC roles, so the runner drops the rest.
    requires_gcc_location: ClassVar[bool] = True
    # ATS APIs return `first_published` as posted_at — the original
    # go-live date, often months old even when the role is actively
    # recruiting. We don't want the runner's date-window gate to drop
    # these. Companies remove closed roles from the API immediately,
    # so "still in the API" = "still hiring".
    requires_recent_posted_at: ClassVar[bool] = False
    # Subclasses set `boards_env_var` to the env var name they read.
    boards_env_var: ClassVar[str] = ""
    default_boards: ClassVar[tuple[str, ...]] = ()

    async def boards(self) -> tuple[str, ...]:
        """Return the merged board-slug list.

        Precedence:
          * If JC_*_BOARDS is set: use those slugs, plus any DB-discovered
            ones (env never *replaces* DB entirely so partial overrides work).
          * Else if any DB-discovered slugs: use those + default_boards.
          * Else: just default_boards.

        When the merged list is empty, log a clear warning at WARNING
        level. Several ATS sources (lever, recruitee, personio,
        smartrecruiters, ashby, successfactors, workday) ship with an
        empty `default_boards` seed: they're meant to be populated via
        env vars or `discover --ats`. If neither has happened, the
        crawler completes silently with 0 fetches — looking healthy in
        `crawl_runs` while contributing nothing. The warning makes that
        misconfiguration obvious in journalctl without changing the
        crawler's behaviour (a quiet no-op is still the right action
        when there's nothing to fetch).
        """
        env_slugs = env_board_slugs(self.boards_env_var, ())
        db_slugs: tuple[str, ...] = ()
        if self.db is not None and self.source_slug:
            try:
                db_slugs = await db_boards_for(self.db, self.source_slug)
            except Exception:
                # Failing to read DB boards must not break the crawl.
                db_slugs = ()
        if env_slugs:
            merged = merge_board_lists(env_slugs, db_slugs)
        elif db_slugs:
            merged = merge_board_lists(db_slugs, self.default_boards)
        else:
            merged = self.default_boards
        if not merged:
            _LOG.warning(
                "%s: no boards configured (env=%s, db_rows=%d, default=%d). "
                "Set %s=<csv> or run `discover --ats` to populate boards; "
                "until then this crawler will be a no-op.",
                self.source_slug,
                self.boards_env_var or "<unset>",
                len(db_slugs),
                len(self.default_boards),
                self.boards_env_var or "JC_*_BOARDS",
            )
        return merged
