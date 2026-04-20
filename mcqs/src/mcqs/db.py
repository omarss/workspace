"""Psycopg connection pool shared by the ingest worker, generator, and API."""

from __future__ import annotations

import atexit
import contextlib
from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg_pool import ConnectionPool

from .config import settings

_pool: ConnectionPool | None = None


def _close_pool() -> None:
    """Explicit close at interpreter exit.

    Python 3.14's finalizer ordering is stricter than 3.12/3.13 and
    `ConnectionPool.__del__` can race with thread teardown, producing a
    `PythonFinalizationError`. Closing explicitly via atexit sidesteps
    the race without changing how callers use the pool."""
    global _pool
    if _pool is not None:
        with contextlib.suppress(Exception):
            _pool.close()
        _pool = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=8,
            kwargs={"autocommit": False},
            open=True,
        )
        atexit.register(_close_pool)
    return _pool


@contextmanager
def connection() -> Iterator[Connection]:
    with pool().connection() as conn:
        yield conn
