"""Breakage detection — auto-disables a source when three independent
signals trip.

Called by the runner after every run. The actual thresholds live here so
A/B-ing them is a single edit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from job_crawler_db import JobCrawlerDB

_LOG: Final = logging.getLogger("job_crawler.health")

# Tunables — see plan in CLAUDE.md / AGENTS.md.
PARSE_RATE_FLOOR: Final = 0.25  # absolute floor — below this it's broken
PARSE_RATE_DROP_FACTOR: Final = 0.50  # if rolling rate falls below baseline * this
CANARY_FAILURES_BREAK: Final = 2  # consecutive failures to declare broken


@dataclass(slots=True)
class RunStats:
    """What the runner accumulated during one execution.

    `quality_rejects` is keyed by `QualityReject.reason` so each gate's
    impact is visible at a glance in the per-run health snapshot. The
    sum of values is also the headline "noise dropped this run" number.
    """

    fetched: int = 0
    parsed: int = 0
    field_coverage_sum: float = 0.0  # sum of per-posting field_coverage()
    quality_rejects: dict[str, int] = field(default_factory=dict)

    @property
    def parse_rate(self) -> float | None:
        return self.parsed / self.fetched if self.fetched else None

    @property
    def field_fill_rate(self) -> float | None:
        return self.field_coverage_sum / self.parsed if self.parsed else None

    def record_quality_reject(self, reason: str) -> None:
        """Bump the counter for `reason` (init to 0 if first sighting)."""
        self.quality_rejects[reason] = self.quality_rejects.get(reason, 0) + 1


async def record_run_outcome(
    db: JobCrawlerDB,
    source_id: UUID,
    stats: RunStats,
) -> None:
    """Persist per-run health stats and trip breakage flags if thresholds fire."""
    psr = stats.parse_rate
    ffr = stats.field_fill_rate
    succeeded = psr is not None and psr >= PARSE_RATE_FLOOR
    await db.crawler_health.upsert_run(
        source_id,
        parse_success_rate=psr,
        field_fill_rate=ffr,
        succeeded=succeeded,
    )
    if psr is not None and psr < PARSE_RATE_FLOOR:
        await db.crawler_health.mark_broken(
            source_id,
            signal="parse_rate",
            reason=(
                f"parse_success_rate={psr:.2f} < floor {PARSE_RATE_FLOOR}. "
                f"{stats.parsed}/{stats.fetched} parsed."
            ),
        )
        _LOG.warning("source %s marked broken (parse_rate)", source_id)


async def record_canary(
    db: JobCrawlerDB,
    source_id: UUID,
    *,
    ok: bool,
    error: str | None = None,
) -> None:
    """Record one canary outcome; auto-disable on 2 consecutive failures."""
    health = await db.crawler_health.record_canary(source_id, ok=ok, error=error)
    if not ok and health.canary_consecutive_failures >= CANARY_FAILURES_BREAK:
        await db.crawler_health.mark_broken(
            source_id,
            signal="canary",
            reason=(
                f"canary failed {health.canary_consecutive_failures} times in a row. "
                f"Last error: {error or 'unknown'}"
            ),
        )
        _LOG.warning("source %s marked broken (canary)", source_id)
