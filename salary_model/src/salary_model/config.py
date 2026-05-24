"""Centralized configuration and logging setup.

Everything that varies between runs (paths, seeds, sizes) lives here. No magic numbers
should appear inline in the modeling code; if you need one, put it here with a name and
a comment explaining the rationale.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Process-wide settings; override via env vars or `.env` (gitignored)."""

    model_config = SettingsConfigDict(
        env_prefix="SALARY_MODEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Paths ─────────────────────────────────────────────────────────────────
    repo_root: Path = REPO_ROOT
    data_dir: Path = REPO_ROOT / "data"
    raw_dir: Path = REPO_ROOT / "data" / "raw"
    seed_dir: Path = REPO_ROOT / "data" / "seed"
    interim_dir: Path = REPO_ROOT / "data" / "interim"
    processed_dir: Path = REPO_ROOT / "data" / "processed"
    artifacts_dir: Path = REPO_ROOT / "artifacts"
    reports_dir: Path = REPO_ROOT / "reports"
    mlruns_dir: Path = REPO_ROOT / "mlruns"

    # ── Reproducibility ───────────────────────────────────────────────────────
    seed: int = 17

    # ── Synthetic dataset size ────────────────────────────────────────────────
    # Tuned so `make iterate` runs the full ladder in under five minutes on CPU.
    synthetic_n_rows: int = Field(default=25_000, ge=1_000, le=1_000_000)

    # ── Train / val / test split (temporal) ───────────────────────────────────
    val_fraction: float = 0.15
    test_fraction: float = 0.15

    # ── Quantile bundle ───────────────────────────────────────────────────────
    quantiles: tuple[float, ...] = (0.1, 0.25, 0.5, 0.75, 0.9)

    # ── Conformal target coverage levels ──────────────────────────────────────
    coverage_targets: tuple[float, ...] = (0.80, 0.90)

    # ── Fairness thresholds (recommendation head must not exceed) ─────────────
    fairness_median_abs_gap_max_pct: float = 0.02  # 2% on TCC p50, counterfactual flip
    fairness_segment_gap_max_pct: float = 0.03

    # ── Retrieval blend policy ────────────────────────────────────────────────
    retrieval_min_strong: int = 50
    retrieval_min_blend: int = 20
    retrieval_min_recommend: int = 5

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_json: bool = False

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir,
            self.raw_dir,
            self.seed_dir,
            self.interim_dir,
            self.processed_dir,
            self.artifacts_dir,
            self.reports_dir,
            self.mlruns_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide singleton settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings


_LOGGING_CONFIGURED = False


def configure_logging(level: str | None = None, *, as_json: bool | None = None) -> None:
    """Configure structlog + stdlib logging once. Safe to call repeatedly."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    settings = get_settings()
    resolved_level = (level or settings.log_level).upper()
    use_json = as_json if as_json is not None else settings.log_json

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, resolved_level, logging.INFO),
    )

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if use_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, resolved_level, logging.INFO),
        ),
        cache_logger_on_first_use=True,
    )
    _LOGGING_CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a configured structlog logger."""
    configure_logging()
    return structlog.get_logger(name)  # type: ignore[no-any-return]
