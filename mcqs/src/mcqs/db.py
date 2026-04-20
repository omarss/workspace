"""Psycopg connection pool shared by the ingest worker, generator, and API."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg_pool import ConnectionPool

from .config import settings

_pool: ConnectionPool | None = None


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
    return _pool


@contextmanager
def connection() -> Iterator[Connection]:
    with pool().connection() as conn:
        yield conn
