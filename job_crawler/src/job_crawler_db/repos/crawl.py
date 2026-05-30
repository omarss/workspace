"""Crawl-operations repo — runs + per-fetch ledger."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from ..enums import CrawlRunStatus
from ..models import CrawlFetch, CrawlRun
from .base import Repo


class CrawlRepo(Repo):
    # -- runs ------------------------------------------------------------

    async def start_run(
        self,
        source_id: UUID,
        *,
        config: dict[str, Any] | None = None,
    ) -> CrawlRun:
        row = await self._fetchone(
            """
            INSERT INTO crawl_runs (source_id, status, started_at, config)
            VALUES (%(s)s, 'running', now(), %(c)s::jsonb)
            RETURNING *;
            """,
            {"s": source_id, "c": json.dumps(config or {}, ensure_ascii=False)},
        )
        assert row is not None
        return CrawlRun.model_validate(row)

    async def sweep_stale_runs(
        self,
        source_id: UUID,
        *,
        max_age_minutes: int,
    ) -> int:
        """Cancel any `running` crawl_runs row for this source older than
        `max_age_minutes`. Returns the number of rows transitioned.

        Why: a crawler process killed by OOM, systemd timeout, or an
        uncaught exception that escaped the finally-block can leave its
        `crawl_runs` row stuck on `status='running'` forever. Those
        rows skew health gauges, accumulate forever, and break the
        "current run" telemetry that ops dashboards depend on.

        Called at the start of each new run for the SAME source — the
        sweep is scoped to the source_id so two crawlers running in
        parallel for different sources don't cancel each other's
        legitimate in-flight runs. The age threshold MUST be greater
        than the longest valid run for that source (otherwise the
        sweep will cancel a still-healthy run).
        """
        rows = await self._fetchall(
            """
            UPDATE crawl_runs
            SET status = 'cancelled',
                finished_at = now(),
                error_summary = COALESCE(
                    error_summary,
                    'cancelled by runner sweep: still running after '
                    || %(m)s::int || ' minutes'
                )
            WHERE source_id = %(s)s
              AND status = 'running'
              AND started_at < now() - (%(m)s::int * INTERVAL '1 minute')
            RETURNING id;
            """,
            {"s": source_id, "m": max_age_minutes},
        )
        return len(rows)

    async def finish_run(
        self,
        run_id: UUID,
        *,
        status: CrawlRunStatus = CrawlRunStatus.completed,
        error_summary: str | None = None,
    ) -> CrawlRun:
        row = await self._fetchone(
            """
            UPDATE crawl_runs SET status = %(st)s,
                                  finished_at = now(),
                                  error_summary = COALESCE(%(es)s, error_summary)
            WHERE id = %(id)s
            RETURNING *;
            """,
            {"id": run_id, "st": status.value, "es": error_summary},
        )
        if row is None:
            raise KeyError(f"Crawl run {run_id} not found")
        return CrawlRun.model_validate(row)

    async def get_run(self, run_id: UUID) -> CrawlRun | None:
        row = await self._fetchone(
            "SELECT * FROM crawl_runs WHERE id = %(id)s",
            {"id": run_id},
        )
        return self._to_model(CrawlRun, row)

    async def increment_counter(
        self,
        run_id: UUID,
        *,
        pages: int = 0,
        seen: int = 0,
        new: int = 0,
        errors: int = 0,
    ) -> None:
        """Atomic counter bumps. Pass any combination of the four."""
        await self._execute(
            """
            UPDATE crawl_runs SET
                pages_fetched = pages_fetched + %(p)s,
                postings_seen = postings_seen + %(se)s,
                postings_new  = postings_new  + %(n)s,
                error_count   = error_count   + %(e)s
            WHERE id = %(id)s;
            """,
            {"id": run_id, "p": pages, "se": seen, "n": new, "e": errors},
        )

    # -- per-fetch ledger -----------------------------------------------

    async def record_fetch(
        self,
        run_id: UUID,
        source_id: UUID,
        url: str,
        *,
        outcome: str,
        posting_id: UUID | None = None,
        http_status: int | None = None,
        duration_ms: int | None = None,
        bytes: int | None = None,
        error_message: str | None = None,
    ) -> CrawlFetch:
        """Append a fetch row. Cheap; expected to be called once per HTTP call.

        `outcome` is one of: 'created' | 'updated' | 'unchanged' | 'error'.
        """
        row = await self._fetchone(
            """
            INSERT INTO crawl_fetches
              (run_id, source_id, posting_id, url, http_status,
               duration_ms, bytes, outcome, error_message)
            VALUES (%(r)s, %(s)s, %(p)s, %(u)s, %(hs)s,
                    %(dms)s, %(b)s, %(o)s, %(em)s)
            RETURNING *;
            """,
            {
                "r": run_id,
                "s": source_id,
                "p": posting_id,
                "u": url,
                "hs": http_status,
                "dms": duration_ms,
                "b": bytes,
                "o": outcome,
                "em": error_message,
            },
        )
        assert row is not None
        return CrawlFetch.model_validate(row)
