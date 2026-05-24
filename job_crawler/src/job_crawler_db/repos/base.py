"""Shared helpers for repos.

A repo is a thin async class that takes a pool in its constructor and
exposes one method per business operation. SQL stays inline so it is
greppable and the type of every column flows through to mypy via the
pydantic models in `models.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


class Repo:
    """Base for every repo. Owns nothing but a reference to the shared pool."""

    __slots__ = ("_pool",)

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    # -- low-level execute helpers ---------------------------------------

    async def _fetchone(
        self,
        sql: str,
        params: Mapping[str, Any] | Sequence[Any] | None = None,
    ) -> dict[str, Any] | None:
        """Execute and return one row as a plain dict, or None."""
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)  # type: ignore[arg-type]
            return await cur.fetchone()

    async def _fetchall(
        self,
        sql: str,
        params: Mapping[str, Any] | Sequence[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute and return every row as a list of dicts."""
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)  # type: ignore[arg-type]
            return await cur.fetchall()

    async def _execute(
        self,
        sql: str,
        params: Mapping[str, Any] | Sequence[Any] | None = None,
    ) -> int:
        """Execute a statement that returns no rows; return affected row count."""
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(sql, params)  # type: ignore[arg-type]
            return cur.rowcount

    async def _stream(
        self,
        sql: str,
        params: Mapping[str, Any] | Sequence[Any] | None = None,
        *,
        batch_size: int = 500,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream rows with a server-side cursor.

        Use for large result sets (the dedupe pipeline, mass exports).
        Avoids materialising every row in memory.
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row, name="jcdb_stream") as cur:
                await cur.execute(sql, params)  # type: ignore[arg-type]
                while batch := await cur.fetchmany(batch_size):
                    for row in batch:
                        yield row

    # -- model materialisation ------------------------------------------

    @staticmethod
    def _to_model(model_cls: type[M], row: Mapping[str, Any] | None) -> M | None:
        return model_cls.model_validate(row) if row is not None else None

    @staticmethod
    def _to_models(model_cls: type[M], rows: list[Mapping[str, Any]]) -> list[M]:
        return [model_cls.model_validate(r) for r in rows]

    # -- transaction context --------------------------------------------

    def transaction(self) -> _TxContext:
        """Run a block of statements in a single transaction.

        Usage:
            async with db.companies.transaction() as conn:
                ...
        The yielded `conn` is an `AsyncConnection` whose transaction the
        context manager commits / rolls back. All other repo calls inside
        the `async with` block borrow their own connections — pass `conn`
        explicitly to a repo method's `conn=` parameter to share the
        transaction. Most callers never need this.
        """
        return _TxContext(self._pool)


class _TxContext:
    """Async context manager that yields a pooled connection inside a tx."""

    __slots__ = ("_conn", "_conn_ctx", "_pool", "_tx_ctx")

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool
        self._conn: psycopg.AsyncConnection[dict[str, Any]] | None = None
        self._conn_ctx: Any = None
        self._tx_ctx: Any = None

    async def __aenter__(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        self._conn_ctx = self._pool.connection()
        self._conn = await self._conn_ctx.__aenter__()
        self._tx_ctx = self._conn.transaction()
        await self._tx_ctx.__aenter__()
        return self._conn

    async def __aexit__(self, *exc: Any) -> None:
        try:
            await self._tx_ctx.__aexit__(*exc)
        finally:
            await self._conn_ctx.__aexit__(*exc)
