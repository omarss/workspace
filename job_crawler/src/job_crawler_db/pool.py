"""Async connection pool wrapper.

Centralises pool construction and the per-session SETs we apply on every
connection check-out so the rest of the library can assume a known runtime
state (statement timeout, trigram thresholds, search path).
"""

from __future__ import annotations

import logging
from typing import Final

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .settings import Settings

_LOG: Final = logging.getLogger(__name__)


async def _configure_session(conn: psycopg.AsyncConnection[dict[str, object]]) -> None:
    """Apply per-session state every connection inherits.

    Runs once when psycopg checks a connection out of the pool for the first
    time (psycopg_pool calls this `configure` callback exactly once per
    physical connection).
    """
    # Make every row a dict by default. Repos that want typed rows override
    # via `cur.row_factory = class_row(SomeClass)` per-cursor — cheap.
    conn.row_factory = dict_row  # type: ignore[assignment]


async def _on_checkout(
    conn: psycopg.AsyncConnection[dict[str, object]],
    *,
    statement_timeout_ms: int,
    trgm_similarity: float,
    trgm_word_similarity: float,
) -> None:
    """Reset per-call session state on every check-out.

    We re-apply these on every check-out (not just once in `configure`) so
    a query that mutates them with `SET LOCAL` doesn't leak across borrowers.
    """
    # Postgres' `SET` is a utility statement and does NOT support bind
    # parameters at the protocol level — we have to format the values into
    # the SQL string. Safe here because all three values originate from our
    # typed `Settings` object, never from user input.
    sti = int(statement_timeout_ms)
    sim = float(trgm_similarity)
    wsim = float(trgm_word_similarity)
    async with conn.cursor() as cur:
        await cur.execute(f"SET statement_timeout = {sti}")
        await cur.execute(f"SET pg_trgm.similarity_threshold = {sim}")
        await cur.execute(f"SET pg_trgm.word_similarity_threshold = {wsim}")


def build_pool(settings: Settings) -> AsyncConnectionPool:
    """Construct (but do not open) an `AsyncConnectionPool`.

    Caller is responsible for `await pool.open()` / `await pool.close()` —
    the `JobCrawlerDB` facade does this in its async context manager.
    """
    # Bake application_name into the DSN if it's not already set.
    dsn = settings.dsn
    if "application_name" not in dsn:
        sep = "&" if "?" in dsn else "?"
        dsn = f"{dsn}{sep}application_name={settings.application_name}"

    sti = settings.statement_timeout_ms
    sim = settings.trgm_similarity_threshold
    wsim = settings.trgm_word_similarity_threshold

    async def _check(conn: psycopg.AsyncConnection[dict[str, object]]) -> None:
        await _on_checkout(
            conn,
            statement_timeout_ms=sti,
            trgm_similarity=sim,
            trgm_word_similarity=wsim,
        )

    return AsyncConnectionPool(
        conninfo=dsn,
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
        timeout=settings.pool_timeout,
        max_idle=settings.pool_max_idle,
        max_lifetime=settings.pool_max_lifetime,
        configure=_configure_session,
        check=_check,
        open=False,  # caller opens explicitly so failures surface in the right place
    )
