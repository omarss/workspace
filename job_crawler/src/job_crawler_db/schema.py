"""Schema bootstrap.

`apply_schema()` reads the bundled `db_schema.sql` and executes it. Use it
in tests and for first-time DB setup. It is **not** a migration tool — for
versioned migrations bring your own (Alembic, Atlas, sqitch, etc.).
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import psycopg


def schema_sql() -> str:
    """Return the bundled `db_schema.sql` as a string.

    Loads from the package first (installed wheel), falls back to the repo
    root for editable installs / source checkouts.
    """
    # Try the installed-package location first.
    try:
        return (resources.files("job_crawler_db") / "db_schema.sql").read_text("utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        pass

    # Fall back to walking up from this file to find the repo's db_schema.sql.
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        candidate = parent / "db_schema.sql"
        if candidate.is_file():
            return candidate.read_text("utf-8")

    raise FileNotFoundError("db_schema.sql not found in the package or any parent directory.")


async def apply_schema(conn: psycopg.AsyncConnection[object]) -> None:
    """Apply the full schema to `conn`'s database.

    The schema file is idempotent on extensions but not on tables/types — so
    only call this against a fresh database. Tests use a throwaway DB per
    session; production setup should run this once during provisioning.

    Runs in a single transaction so a mid-file failure rolls everything back.
    """
    sql = schema_sql()
    async with conn.transaction(), conn.cursor() as cur:
        await cur.execute(sql)
