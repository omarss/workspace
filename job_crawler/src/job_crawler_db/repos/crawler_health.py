"""CrawlerHealth repo — auto-detect-breakage state.

Three signals are tracked per source:
  * parse_success_rate     — 7-day rolling parsed/fetched ratio
  * field_fill_rate        — 7-day rolling required-field coverage
  * canary_consecutive_failures — synthetic always-parseable URL checks

When any threshold trips, the row's `broken_since` is set and the matching
`sources.crawl_enabled` is flipped to false in the same transaction.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from .base import Repo


class CrawlerHealth(BaseModel):
    source_id: UUID
    crawler_version: str
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    parse_success_rate: Decimal | None = None
    field_fill_rate: Decimal | None = None
    canary_last_at: datetime | None = None
    canary_ok: bool | None = None
    canary_consecutive_failures: int = 0
    canary_last_error: str | None = None
    broken_since: datetime | None = None
    breakage_reason: str | None = None
    breakage_signal: str | None = None
    updated_at: datetime


class CrawlerHealthRepo(Repo):
    async def get(self, source_id: UUID) -> CrawlerHealth | None:
        row = await self._fetchone(
            "SELECT * FROM crawler_health WHERE source_id = %(s)s",
            {"s": source_id},
        )
        return CrawlerHealth.model_validate(row) if row else None

    async def upsert_run(
        self,
        source_id: UUID,
        *,
        parse_success_rate: float | None = None,
        field_fill_rate: float | None = None,
        ran_at: datetime | None = None,
        succeeded: bool = True,
    ) -> CrawlerHealth:
        """Record a per-run summary. Resets canary failure counter on success."""
        row = await self._fetchone(
            """
            INSERT INTO crawler_health
              (source_id, last_run_at, last_success_at,
               parse_success_rate, field_fill_rate)
            VALUES (%(s)s, COALESCE(%(t)s, now()),
                    CASE WHEN %(ok)s THEN COALESCE(%(t)s, now()) END,
                    %(psr)s, %(ffr)s)
            ON CONFLICT (source_id) DO UPDATE SET
                last_run_at        = EXCLUDED.last_run_at,
                last_success_at    = COALESCE(EXCLUDED.last_success_at, crawler_health.last_success_at),
                parse_success_rate = COALESCE(EXCLUDED.parse_success_rate, crawler_health.parse_success_rate),
                field_fill_rate    = COALESCE(EXCLUDED.field_fill_rate, crawler_health.field_fill_rate)
            RETURNING *;
            """,
            {
                "s": source_id,
                "t": ran_at,
                "ok": succeeded,
                "psr": Decimal(str(parse_success_rate)) if parse_success_rate is not None else None,
                "ffr": Decimal(str(field_fill_rate)) if field_fill_rate is not None else None,
            },
        )
        assert row is not None
        return CrawlerHealth.model_validate(row)

    async def record_canary(
        self,
        source_id: UUID,
        *,
        ok: bool,
        error: str | None = None,
        ran_at: datetime | None = None,
    ) -> CrawlerHealth:
        """Record a canary outcome. Increments the failure counter on failure;
        resets to zero on success."""
        row = await self._fetchone(
            """
            INSERT INTO crawler_health
              (source_id, canary_last_at, canary_ok,
               canary_consecutive_failures, canary_last_error)
            VALUES (%(s)s, COALESCE(%(t)s, now()), %(ok)s,
                    CASE WHEN %(ok)s THEN 0 ELSE 1 END, %(err)s)
            ON CONFLICT (source_id) DO UPDATE SET
                canary_last_at    = COALESCE(EXCLUDED.canary_last_at, crawler_health.canary_last_at),
                canary_ok         = EXCLUDED.canary_ok,
                canary_consecutive_failures = CASE
                    WHEN EXCLUDED.canary_ok THEN 0
                    ELSE crawler_health.canary_consecutive_failures + 1
                END,
                canary_last_error = EXCLUDED.canary_last_error
            RETURNING *;
            """,
            {"s": source_id, "t": ran_at, "ok": ok, "err": error},
        )
        assert row is not None
        return CrawlerHealth.model_validate(row)

    async def mark_broken(
        self,
        source_id: UUID,
        *,
        signal: str,  # 'canary' | 'parse_rate' | 'field_fill' | 'manual'
        reason: str,
    ) -> CrawlerHealth:
        """Set broken_since + disable the source. Idempotent: a second call
        on an already-broken source keeps the original broken_since."""
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE sources SET crawl_enabled = false WHERE id = %(s)s",
                        {"s": source_id},
                    )
                from psycopg.rows import dict_row

                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        INSERT INTO crawler_health
                          (source_id, broken_since, breakage_reason, breakage_signal)
                        VALUES (%(s)s, now(), %(reason)s, %(signal)s)
                        ON CONFLICT (source_id) DO UPDATE SET
                            broken_since    = COALESCE(crawler_health.broken_since, EXCLUDED.broken_since),
                            breakage_reason = EXCLUDED.breakage_reason,
                            breakage_signal = EXCLUDED.breakage_signal
                        RETURNING *;
                        """,
                        {"s": source_id, "reason": reason, "signal": signal},
                    )
                    row = await cur.fetchone()
        assert row is not None
        return CrawlerHealth.model_validate(row)

    async def clear_broken(self, source_id: UUID) -> CrawlerHealth | None:
        """Reset broken state — used by canary recovery after a code fix."""
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE sources SET crawl_enabled = true WHERE id = %(s)s",
                        {"s": source_id},
                    )
                from psycopg.rows import dict_row

                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        UPDATE crawler_health
                        SET broken_since = NULL, breakage_reason = NULL, breakage_signal = NULL
                        WHERE source_id = %(s)s
                        RETURNING *;
                        """,
                        {"s": source_id},
                    )
                    row = await cur.fetchone()
        return CrawlerHealth.model_validate(row) if row else None

    async def list_broken(self) -> list[dict[str, Any]]:
        return await self._fetchall(
            """
            SELECT ch.*, s.slug, s.display_name
            FROM crawler_health ch
            JOIN sources s ON s.id = ch.source_id
            WHERE ch.broken_since IS NOT NULL
            ORDER BY ch.broken_since DESC;
            """,
        )
