"""Library settings — read once from the environment, immutable after construction.

The library deliberately does NOT use pydantic-settings (avoids an extra dep);
all knobs are plain class fields with explicit type hints + a `from_env()`
constructor that documents every recognised env var in one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """All runtime configuration for a `JobCrawlerDB` instance.

    Build with `Settings.from_env()` to read the standard env vars, or
    instantiate directly to override per-test / per-call.
    """

    # libpq-style connection string. Everything libpq understands works:
    #   postgresql://user:pass@host:5432/dbname?sslmode=require
    dsn: str

    # Connection pool sizing. Defaults are conservative for a single
    # background crawler worker; bump min/max for high-concurrency ingest.
    pool_min_size: int = 2
    pool_max_size: int = 20

    # Pool timeouts (seconds).
    pool_timeout: float = 30.0  # wait this long for a free connection
    pool_max_idle: float = 600.0  # close connections idle longer than this
    pool_max_lifetime: float = 3600.0  # recycle connections older than this

    # Per-statement timeout applied to every session (SET statement_timeout).
    # 0 disables.
    statement_timeout_ms: int = 30_000

    # When true, set pg_trgm thresholds on every session so search queries
    # don't have to repeat them. Values are saturation points, not minimums
    # the matcher demands — they only affect the `%` / `<%` operators.
    trgm_similarity_threshold: float = 0.30
    trgm_word_similarity_threshold: float = 0.45

    # Application name reported to Postgres. Helps when staring at pg_stat_activity.
    application_name: str = "job_crawler_db"

    @classmethod
    def from_env(cls, *, prefix: str = "JCDB_") -> Settings:
        """Build settings from environment variables.

        Recognised variables (all prefixed with `JCDB_` by default):
          - JCDB_DSN                              (required)
          - JCDB_POOL_MIN_SIZE
          - JCDB_POOL_MAX_SIZE
          - JCDB_POOL_TIMEOUT
          - JCDB_POOL_MAX_IDLE
          - JCDB_POOL_MAX_LIFETIME
          - JCDB_STATEMENT_TIMEOUT_MS
          - JCDB_TRGM_SIMILARITY_THRESHOLD
          - JCDB_TRGM_WORD_SIMILARITY_THRESHOLD
          - JCDB_APPLICATION_NAME

        Falls back to the libpq `PGDATABASE` / `PGUSER` etc. only if `JCDB_DSN`
        is unset *and* `dsn` is given to the call.
        """
        dsn = os.environ.get(f"{prefix}DSN")
        if not dsn:
            raise RuntimeError(f"{prefix}DSN is required. Set it to a libpq connection string.")

        def _int(name: str, default: int) -> int:
            raw = os.environ.get(f"{prefix}{name}")
            return int(raw) if raw is not None else default

        def _float(name: str, default: float) -> float:
            raw = os.environ.get(f"{prefix}{name}")
            return float(raw) if raw is not None else default

        # NB: defaults are inlined here because `cls.pool_min_size` etc. return
        # the slotted-dataclass member descriptors, not the default values.
        # Keep these in sync with the field-default literals above.
        return cls(
            dsn=dsn,
            pool_min_size=_int("POOL_MIN_SIZE", 2),
            pool_max_size=_int("POOL_MAX_SIZE", 20),
            pool_timeout=_float("POOL_TIMEOUT", 30.0),
            pool_max_idle=_float("POOL_MAX_IDLE", 600.0),
            pool_max_lifetime=_float("POOL_MAX_LIFETIME", 3600.0),
            statement_timeout_ms=_int("STATEMENT_TIMEOUT_MS", 30_000),
            trgm_similarity_threshold=_float("TRGM_SIMILARITY_THRESHOLD", 0.30),
            trgm_word_similarity_threshold=_float("TRGM_WORD_SIMILARITY_THRESHOLD", 0.45),
            application_name=os.environ.get(f"{prefix}APPLICATION_NAME", "job_crawler_db"),
        )
