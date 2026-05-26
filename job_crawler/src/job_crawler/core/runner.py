"""CrawlerRunner — orchestrates one full execution of a BaseCrawler.

Lifecycle (per run):
  1. ensure the source row exists in `sources`
  2. start a `crawl_runs` row (status=running)
  3. iterate listings since the cutoff date
     for each: fetch_detail → parse → normalize → upsert posting
              → resolve+attach company → write side-data
              → record a `crawl_fetches` row
  4. finish the run (status=completed | failed) and update counters
  5. record health stats; flip broken flags if thresholds fire
  6. send alert email on transition from healthy→broken (when SMTP wired)

The runner is the only thing that touches the DB write surface; per-site
crawlers stay pure (parse + normalize).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final
from uuid import UUID

from job_crawler_db import (
    CrawlRunStatus,
    JobCrawlerDB,
    JobPostingUpsert,
    SourceKind,
)

from .base import BaseCrawler
from .date_window import cutoff, is_within_window
from .geo_filter import is_gcc_location
from .health import RunStats, record_run_outcome
from .normalise import field_coverage, persist_side_data, resolve_city, to_upsert
from .quality import check_intra_run_dup, check_listing, check_parsed
from .types import Listing, ParsedPosting

_LOG: Final = logging.getLogger("job_crawler.runner")


@dataclass(slots=True)
class RunSummary:
    """Returned by `CrawlerRunner.run()` for the CLI / caller."""

    source_slug: str
    run_id: UUID
    fetched: int
    parsed: int
    new_postings: int
    updated_postings: int
    errors: int
    status: CrawlRunStatus


class CrawlerRunner:
    """Drives one BaseCrawler instance through one full execution."""

    __slots__ = ("_source_id", "crawler", "db")

    def __init__(self, db: JobCrawlerDB, crawler: BaseCrawler) -> None:
        self.db = db
        self.crawler = crawler
        self._source_id: UUID | None = None

    async def ensure_source(self) -> UUID:
        """Idempotent: create the source row on first run."""
        if self._source_id is not None:
            return self._source_id
        source = await self.db.sources.upsert(
            slug=self.crawler.source_slug,
            display_name=self.crawler.source_display_name,
            kind=self.crawler.source_kind,
            base_url=self.crawler.source_base_url,
            trust_weight=self.crawler.source_trust_weight,
        )
        self._source_id = source.id
        return source.id

    async def run(self) -> RunSummary:
        """Execute one full crawl cycle.

        Idempotent in the sense that repeated runs don't duplicate postings
        (postings.upsert dedupes on source+external_id). New runs do create
        new `crawl_runs` rows for forensics.
        """
        source_id = await self.ensure_source()

        run = await self.db.crawl.start_run(
            source_id,
            config={
                "crawler_version": self.crawler.crawler_version,
                "lookback_cutoff": cutoff().isoformat(),
            },
        )
        stats = RunStats()
        new_count = 0
        updated_count = 0
        errors = 0
        since = cutoff()
        # Intra-run dedup set, scoped to this single run. Catches
        # paginators that surface the same listing on multiple pages.
        seen_content_hashes: set[bytes] = set()

        try:
            async for listing in self._safe_iter(self.crawler.discover_listings(since=since)):
                # Listing-stage gate: skip nav / search URLs before paying
                # for a fetch. We don't bump `fetched` (no HTTP happened)
                # and don't record_fetch (no URL was fetched).
                listing_reject = check_listing(listing)
                if listing_reject is not None:
                    stats.record_quality_reject(listing_reject.reason)
                    _LOG.debug(
                        "listing rejected (%s): %s — %s",
                        listing_reject.reason,
                        listing.detail_url,
                        listing_reject.detail,
                    )
                    continue
                stats.fetched += 1
                try:
                    raw = await self.crawler.fetch_detail(listing)
                except Exception:
                    _LOG.exception("fetch_detail failed for %s", listing.detail_url)
                    errors += 1
                    await self.db.crawl.record_fetch(
                        run.id,
                        source_id,
                        listing.detail_url,
                        outcome="error",
                        error_message="fetch_detail raised",
                    )
                    continue
                if raw is None:
                    errors += 1
                    await self.db.crawl.record_fetch(
                        run.id,
                        source_id,
                        listing.detail_url,
                        outcome="error",
                        error_message="fetch_detail returned None",
                    )
                    continue

                # Parse + 30-day cutoff.
                parsed = self._safe_parse(raw)
                if parsed is None:
                    await self.db.crawl.record_fetch(
                        run.id,
                        source_id,
                        raw.canonical_url,
                        outcome="error",
                        http_status=raw.http_status,
                        duration_ms=raw.duration_ms,
                        bytes=raw.bytes,
                        error_message="parse returned None",
                    )
                    continue
                stats.parsed += 1
                stats.field_coverage_sum += field_coverage(parsed)
                # GCC-only geo filter for ATS crawlers — boards are already
                # SA-scoped by their search URLs and skip this check.
                if (
                    self.crawler.requires_gcc_location
                    and not is_gcc_location(parsed.raw_location,
                                            country_code=parsed.country_code)
                ):
                    await self.db.crawl.record_fetch(
                        run.id, source_id, raw.canonical_url,
                        outcome="unchanged",
                        http_status=raw.http_status,
                        duration_ms=raw.duration_ms, bytes=raw.bytes,
                        error_message="non-GCC location",
                    )
                    continue
                if not is_within_window(parsed.posted_at):
                    # Older than the lookback — skip, but still count the fetch.
                    await self.db.crawl.record_fetch(
                        run.id,
                        source_id,
                        raw.canonical_url,
                        outcome="unchanged",
                        http_status=raw.http_status,
                        duration_ms=raw.duration_ms,
                        bytes=raw.bytes,
                    )
                    continue

                # Universal post-parse quality gate.
                # First-failed-check wins so the scorecard reason tag is
                # deterministic. New rejection categories (low-diversity
                # description, garbage company name, future posted_at,
                # etc.) all funnel through this single chokepoint.
                parsed_reject = check_parsed(parsed)
                if parsed_reject is not None:
                    stats.record_quality_reject(parsed_reject.reason)
                    await self.db.crawl.record_fetch(
                        run.id,
                        source_id,
                        raw.canonical_url,
                        outcome="rejected",
                        http_status=raw.http_status,
                        duration_ms=raw.duration_ms,
                        bytes=raw.bytes,
                        error_message=(
                            f"quality:{parsed_reject.reason} "
                            f"— {parsed_reject.detail}"
                        ),
                    )
                    continue

                # Intra-run dedup: same description seen twice in this run
                # (paginator overlap, listing surfaced on two query
                # variants, etc.). Cross-run + cross-source dedup is
                # handled later by `intelligence/dedup.py`.
                dup_reject = check_intra_run_dup(
                    parsed,
                    seen_content_hashes=seen_content_hashes,
                )
                if dup_reject is not None:
                    stats.record_quality_reject(dup_reject.reason)
                    await self.db.crawl.record_fetch(
                        run.id,
                        source_id,
                        raw.canonical_url,
                        outcome="rejected",
                        http_status=raw.http_status,
                        duration_ms=raw.duration_ms,
                        bytes=raw.bytes,
                        error_message=(
                            f"quality:{dup_reject.reason} "
                            f"— {dup_reject.detail}"
                        ),
                    )
                    continue

                # Resolve company + city (best-effort) and upsert the posting.
                try:
                    posting_id, was_new = await self._upsert_with_sides(
                        source_id,
                        parsed,
                    )
                except Exception:
                    _LOG.exception("upsert failed for %s", parsed.canonical_url)
                    errors += 1
                    await self.db.crawl.record_fetch(
                        run.id,
                        source_id,
                        raw.canonical_url,
                        outcome="error",
                        http_status=raw.http_status,
                        duration_ms=raw.duration_ms,
                        bytes=raw.bytes,
                        error_message="upsert raised",
                    )
                    continue

                if was_new:
                    new_count += 1
                else:
                    updated_count += 1
                await self.db.crawl.record_fetch(
                    run.id,
                    source_id,
                    raw.canonical_url,
                    posting_id=posting_id,
                    outcome="created" if was_new else "updated",
                    http_status=raw.http_status,
                    duration_ms=raw.duration_ms,
                    bytes=raw.bytes,
                )
        except Exception:
            _LOG.exception("run %s aborted", run.id)
            await self.db.crawl.finish_run(
                run.id,
                status=CrawlRunStatus.failed,
                error_summary="runner raised",
            )
            await record_run_outcome(self.db, source_id, stats)
            return RunSummary(
                source_slug=self.crawler.source_slug,
                run_id=run.id,
                fetched=stats.fetched,
                parsed=stats.parsed,
                new_postings=new_count,
                updated_postings=updated_count,
                errors=errors + 1,
                status=CrawlRunStatus.failed,
            )

        await self.db.crawl.increment_counter(
            run.id,
            pages=stats.fetched,
            seen=stats.fetched,
            new=new_count,
            errors=errors,
        )
        await self.db.crawl.finish_run(run.id, status=CrawlRunStatus.completed)
        await record_run_outcome(self.db, source_id, stats)

        return RunSummary(
            source_slug=self.crawler.source_slug,
            run_id=run.id,
            fetched=stats.fetched,
            parsed=stats.parsed,
            new_postings=new_count,
            updated_postings=updated_count,
            errors=errors,
            status=CrawlRunStatus.completed,
        )

    # ---- internals ----------------------------------------------------

    async def _safe_iter(self, it: AsyncIterator[Listing]) -> AsyncIterator[Listing]:
        """Wrap discover_listings so a single yield exception doesn't kill the run."""
        try:
            async for item in it:
                yield item
        except Exception:
            _LOG.exception("discover_listings raised; finishing the partial batch")

    def _safe_parse(self, raw: object) -> ParsedPosting | None:
        try:
            return self.crawler.parse(raw)  # type: ignore[arg-type]
        except Exception:
            _LOG.exception("parse raised")
            return None

    async def _upsert_with_sides(
        self,
        source_id: UUID,
        parsed: ParsedPosting,
    ) -> tuple[UUID, bool]:
        """Resolve company + city, upsert the posting, persist side-data.
        Returns (posting_id, was_new_insert)."""
        from .normalise import _clean_company_name

        # Clean the company name BEFORE calling resolve — otherwise a
        # garbage typo like 'Qwer0770&' creates a real `companies` row
        # via the fuzzy resolver. `to_upsert` runs later and only
        # sanitises the posting field, not the entity.
        clean_company = _clean_company_name(parsed.raw_company_name)
        company_id: UUID | None = None
        if clean_company:
            company = await self.db.companies.resolve(
                raw_name=clean_company,
                source_id=source_id,
                source_company_external_id=parsed.company_external_id,
                source_profile_url=parsed.company_profile_url,
            )
            company_id = company.id

        recruiter_id: UUID | None = None
        if parsed.poster_linkedin_url or parsed.raw_poster_name:
            recruiter = await self.db.recruiters.resolve(
                linkedin_url=parsed.poster_linkedin_url,
                full_name=parsed.raw_poster_name,
            )
            recruiter_id = recruiter.id

        location = await resolve_city(
            self.db,
            parsed.city_name_hint,
            raw_location=parsed.raw_location,
            country_code=parsed.country_code or None,
        )
        upsert: JobPostingUpsert = to_upsert(
            parsed,
            source_id=source_id,
            company_id=company_id,
            recruiter_id=recruiter_id,
            location=location,
        )
        # Was this an insert? Easiest test: check by external id before/after.
        existing = await self.db.postings.get_by_source(
            source_id,
            parsed.source_job_external_id,
        )
        was_new = existing is None
        posting = await self.db.postings.upsert(upsert)
        await persist_side_data(
            self.db,
            posting.id,
            channels=parsed.application_channels,
            raw_skills=parsed.raw_skills,
        )

        # First-cluster bootstrap: every posting needs at least its own
        # 1-posting cluster so it shows up in search. The dedupe pipeline
        # (later phase) can merge clusters via posting_duplicate_edges.
        if was_new:
            try:
                await self.db.jobs.create_from_posting(posting.id)
            except Exception:
                _LOG.exception("create_from_posting failed for %s", posting.id)
        return posting.id, was_new


# Keep the imports alive for downstream code-completion. Each goes
# under a distinct `_KEEP_*` name so mypy doesn't try to unify the
# types under a single bare `_`.
_KEEP_SOURCE_KIND = SourceKind
_KEEP_DATETIME = datetime
_KEEP_TIMEZONE = timezone
