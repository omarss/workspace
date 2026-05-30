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
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
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

# Default freshness window (hours) for the incremental-crawl skip. With
# a 4-runs-per-day cron, 6 hours catches every cycle without thrashing.
# Set `JC_LISTING_FRESH_HOURS=0` to disable and force every listing to
# be re-fetched (legacy behaviour). Negative values clamp to 0.
_DEFAULT_FRESH_HOURS: Final = 6


# Cap on how long a `crawl_runs` row may stay in `status='running'`
# before the next run for the same source sweeps it to `cancelled`.
# Must exceed the longest legitimate run for any source. The hourly
# systemd unit's TimeoutStartSec is 90 minutes; company_careers is
# scheduled every 4 hours but each run can also be long. 240 minutes
# (4 hours) is a safe ceiling that still cleans up week-old zombies.
_DEFAULT_STALE_RUN_MINUTES: Final = 240


def _stale_run_minutes() -> int:
    """Read JC_STALE_RUN_MINUTES with a sane fallback. Negative or
    unparseable values clamp to the default — the sweep MUST NOT cancel
    legitimate in-flight runs."""
    raw = os.environ.get("JC_STALE_RUN_MINUTES")
    if raw is None:
        return _DEFAULT_STALE_RUN_MINUTES
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_STALE_RUN_MINUTES
    return parsed if parsed > 0 else _DEFAULT_STALE_RUN_MINUTES


def _get_fresh_hours() -> int:
    """Read JC_LISTING_FRESH_HOURS from env with a sane fallback.

    Returns 0 if the env value is unparseable or negative — that keeps
    the skip disabled rather than crashing the run on a bad config.
    """
    raw = os.environ.get("JC_LISTING_FRESH_HOURS")
    if raw is None:
        return _DEFAULT_FRESH_HOURS
    try:
        return max(0, int(raw))
    except ValueError:
        _LOG.warning(
            "JC_LISTING_FRESH_HOURS=%r is not an integer; disabling skip",
            raw,
        )
        return 0


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
    # Listings discovered but short-circuited by the incremental-crawl
    # freshness skip — they never reached `fetch_detail`, so they don't
    # show up in `fetched` either. Surface them separately so the CLI
    # summary lets operators see how much HTTP budget the skip saved.
    fresh_skipped: int = 0


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

        # Sweep any leftover `running` rows for THIS source whose age
        # exceeds the configured run cap. A crawler killed by OOM,
        # systemd timeout, or an uncaught exception in a non-finally
        # path leaves its `crawl_runs` row stuck on `status='running'`
        # forever; the sweep transitions those to `cancelled` so health
        # gauges and "current run" telemetry stay honest. Scoped to
        # source_id so two concurrent runners on different sources
        # don't step on each other's legitimate runs.
        stale_cap = _stale_run_minutes()
        cancelled = await self.db.crawl.sweep_stale_runs(
            source_id, max_age_minutes=stale_cap,
        )
        if cancelled:
            _LOG.warning(
                "swept %d stale running run(s) older than %dm for source=%s",
                cancelled, stale_cap, self.crawler.source_slug,
            )

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
        # `since` is the discover-stage date hint. For crawlers that honour
        # `posted_at`-based recency (job boards), it's the lookback cutoff
        # so the discover step can server-side-filter old listings. For
        # ATS / company-careers crawlers that bypass the date window
        # (`requires_recent_posted_at=False`), we pass a far-past cutoff —
        # the API only returns currently-hiring roles anyway, so this
        # gets us the full active set and the runner decides per posting.
        since = (
            cutoff()
            if self.crawler.requires_recent_posted_at
            else datetime(1970, 1, 1, tzinfo=UTC)
        )
        # Intra-run dedup set, scoped to this single run. Catches
        # paginators that surface the same listing on multiple pages.
        seen_content_hashes: set[bytes] = set()

        # Incremental-crawl freshness skip. When JC_LISTING_FRESH_HOURS is
        # set to a positive integer, the runner bulk-loads every
        # `source_job_external_id` whose posting was fetched within that
        # window for this source, and short-circuits before `fetch_detail`
        # for any listing already in the set. Defaults to 6h — fits a
        # 4-runs-per-day cron without losing description / status edits
        # that happen quicker than that.
        fresh_hours = _get_fresh_hours()
        fresh_external_ids: set[str] = await self.db.postings.fresh_external_ids(
            source_id, hours=fresh_hours,
        )
        if fresh_external_ids:
            _LOG.info(
                "incremental crawl: %d listings will be skipped if seen "
                "within %dh (source=%s)",
                len(fresh_external_ids), fresh_hours, self.crawler.source_slug,
            )

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
                # Incremental skip: posting was fetched recently, no
                # reason to re-pay the HTTP + Playwright cost. Recorded
                # as `outcome='unchanged'` so the crawl_fetches ledger
                # still reflects that we considered this URL this cycle.
                if listing.source_job_external_id in fresh_external_ids:
                    stats.fresh_skipped += 1
                    await self.db.crawl.record_fetch(
                        run.id,
                        source_id,
                        listing.detail_url,
                        outcome="unchanged",
                        error_message=(
                            f"skipped: fresh within {fresh_hours}h"
                        ),
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
                # Per-source date filter. Job-board crawlers (Bayt, Wuzzuf,
                # Tanqeeb, ...) have honest `posted_at` (listing creation
                # date; old roles get cleaned up by the source). ATS APIs
                # + company careers pages report `first_published` — often
                # months old even when the role is actively recruiting —
                # so they set `requires_recent_posted_at=False` and bypass
                # the window gate entirely. The `telegram_broadcasts`
                # dedup + the "was_new" cluster-create check prevent
                # re-broadcasting an ATS role on subsequent runs.
                if self.crawler.requires_recent_posted_at and not is_within_window(
                    parsed.posted_at,
                    source_updated_at=parsed.source_updated_at,
                ):
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
                fresh_skipped=stats.fresh_skipped,
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
            fresh_skipped=stats.fresh_skipped,
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

            # Telegram channel broadcast — Saudi jobs only, with the
            # authoritative source URL + 3-5 line description summary.
            # Non-fatal: a Telegram outage or missing env must not
            # break the crawl. Fires only for genuinely new clusters,
            # never for re-fetches.
            try:
                await self._maybe_broadcast_new_job(parsed, posting.id, company_id)
            except Exception:
                _LOG.exception("telegram broadcast failed for %s", posting.id)
        return posting.id, was_new

    async def _maybe_broadcast_new_job(
        self,
        parsed: ParsedPosting,
        posting_id: UUID,
        company_id: UUID | None,
    ) -> None:
        """Post a single Telegram message for a newly-ingested Saudi job.

        Quality gate (Telegram is stricter than the DB-ingest gate —
        we want only top-quality posts on the channel):
          * Must be Saudi — `country_code='sa'`.
          * Title must be non-empty.
          * Description must be ≥ 300 chars after cleaning (DB-ingest
            gate allows 100; Telegram raises the bar so short stubs
            don't reach subscribers).
          * Company must be resolved (`company_id IS NOT NULL`) — raw
            company strings without an entity lookup are too noisy.
          * City must be resolved — postings without a known city give
            subscribers nothing to filter on.

        Cluster-level dedup: a row in `telegram_broadcasts` for this
        cluster means we already posted it (in a previous run, or via
        a sibling posting that landed in the same cluster). Skip.

        `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHANNEL_ID` env-driven; missing
        config → silent no-op via `send_message`.
        """
        # --- Quality gates ------------------------------------------------
        # Each gate failure is logged at INFO with a short reason code so
        # operators can answer "why didn't this post hit the channel?"
        # without writing a 30-line CTE against the live DB. The
        # `posting_id` is included so the log line can be cross-referenced
        # with `job_postings`.
        country = (parsed.country_code or "").lower()
        if country != "sa":
            _LOG.info(
                "telegram-gate: posting=%s skipped reason=non_sa country=%r",
                posting_id, country or "?",
            )
            return
        if not parsed.title:
            _LOG.info("telegram-gate: posting=%s skipped reason=empty_title", posting_id)
            return

        posting = await self.db.postings.get(posting_id)
        if posting is None:
            _LOG.info("telegram-gate: posting=%s skipped reason=posting_missing", posting_id)
            return
        if posting.cluster_job_id is None:
            _LOG.info(
                "telegram-gate: posting=%s skipped reason=no_cluster", posting_id,
            )
            return
        if company_id is None:
            _LOG.info(
                "telegram-gate: posting=%s skipped reason=no_company raw=%r",
                posting_id, (parsed.raw_company_name or "")[:60],
            )
            return
        if posting.city_id is None:
            _LOG.info(
                "telegram-gate: posting=%s skipped reason=no_city raw_loc=%r",
                posting_id, (parsed.raw_location or "")[:60],
            )
            return
        desc_len = len((posting.description or "").strip())
        if desc_len < 300:
            _LOG.info(
                "telegram-gate: posting=%s skipped reason=desc_short len=%d",
                posting_id, desc_len,
            )
            return
        # Require a clear date for subscribers. `posted_at` is the
        # canonical signal (board's listing creation date) — we prefer
        # that when present. Some sources (notably `company_careers`,
        # which scrapes SPA career pages) cannot extract a posted-at
        # from the HTML; for those we fall back to `first_seen_at`
        # (when our crawler first ingested the URL), gated to the last
        # 48 hours so a bulk-backfill or re-seed cannot retroactively
        # spam the channel with stale listings. `source_updated_at` is
        # NOT a substitute (Greenhouse refreshes long-lived roles, but
        # the original posted_at is what subscribers expect).
        from datetime import UTC, datetime, timedelta
        display_date: datetime | None = parsed.posted_at
        if display_date is None:
            seen_ts = (
                posting.first_seen_at if posting.first_seen_at.tzinfo
                else posting.first_seen_at.replace(tzinfo=UTC)
            )
            if seen_ts < datetime.now(UTC) - timedelta(hours=48):
                _LOG.info(
                    "telegram-gate: posting=%s skipped reason=stale_no_posted seen=%s",
                    posting_id, seen_ts.isoformat(),
                )
                return
            display_date = seen_ts

        # --- Cluster-level dedup (telegram_broadcasts) --------------------
        async with self.db.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM telegram_broadcasts WHERE job_id = %(j)s",
                {"j": posting.cluster_job_id},
            )
            if await cur.fetchone() is not None:
                _LOG.info(
                    "telegram-gate: posting=%s skipped reason=already_broadcast cluster=%s",
                    posting_id, posting.cluster_job_id,
                )
                return  # already posted

        # --- Resolve display names (single-row indexed lookups) -----------
        company = await self.db.companies.get(company_id)
        company_name = (
            company.name_en if company and company.name_en
            else (company.name_ar if company else None)
        ) or parsed.raw_company_name

        city = await self.db.geo.get_city(posting.city_id)
        city_name = city.name_en if city else None

        from ..alerts.telegram import format_new_job, send_message

        body, buttons = format_new_job(
            title=parsed.title,
            company_name=company_name,
            city_name=city_name,
            country_code="sa",
            category_code=None,
            category_name=None,
            description=parsed.description,
            salary_min=parsed.salary_min,
            salary_max=parsed.salary_max,
            salary_currency=parsed.salary_currency,
            salary_period=(
                parsed.salary_period.value if parsed.salary_period else None
            ),
            posted_at=parsed.posted_at,
            first_seen_at=(
                display_date if parsed.posted_at is None else None
            ),
            url=parsed.canonical_url,
        )
        sent_message_id = await send_message(body, inline_buttons=buttons)
        if sent_message_id is not None:
            # Record successful broadcast so future runs / re-fetches
            # don't repost. INSERT ... ON CONFLICT DO NOTHING in case
            # a concurrent broadcaster won the race (k3s CronJob's
            # concurrencyPolicy=Forbid prevents this, but defend
            # anyway). The `message_id` is persisted so a future
            # edit/delete pipeline can address the original message —
            # the column has existed (nullable) since v1, but nothing
            # was writing to it before.
            from os import environ
            chat_id = environ.get("TELEGRAM_CHANNEL_ID", "").strip()
            # send_message returns -1 as a sentinel for "sent but id
            # unavailable" (non-JSON or unexpected shape). Store NULL in
            # that case so the column's semantics stay clean.
            persisted_id = sent_message_id if sent_message_id >= 0 else None
            async with self.db.pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO telegram_broadcasts (job_id, chat_id, message_id)
                    VALUES (%(j)s, %(c)s, %(m)s)
                    ON CONFLICT (job_id) DO NOTHING;
                    """,
                    {
                        "j": posting.cluster_job_id,
                        "c": chat_id,
                        "m": persisted_id,
                    },
                )
            _LOG.info(
                "telegram-broadcast: posting=%s cluster=%s message_id=%s",
                posting_id, posting.cluster_job_id, persisted_id,
            )


# Keep the imports alive for downstream code-completion. Each goes
# under a distinct `_KEEP_*` name so mypy doesn't try to unify the
# types under a single bare `_`.
_KEEP_SOURCE_KIND = SourceKind
_KEEP_DATETIME = datetime
_KEEP_TIMEZONE = timezone
