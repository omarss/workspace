"""Data quality cleanup that runs before training.

Implements the §16 design rules in a single typed pipeline. Input is any
DataFrame matching the canonical observation schema (the synthetic generator's
output, or anything ingested via a ``data/sources/`` loader). Output is a cleaned
DataFrame plus a typed :class:`CleanupReport` showing what was dropped and why.

The pipeline is **monotonic and idempotent** — running it twice yields the same
result. It is also **explicit**: no operation drops a row without recording the
reason in the report.

Wired into :func:`salary_model.data.build.build_dataset` so every snapshot is
cleaned before it lands on disk; also exposed via the CLI as ``salary-model data
clean`` for ad-hoc runs against an arbitrary Parquet.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from salary_model.config import get_logger

log = get_logger("salary_model.data.cleanup")

# ── Thresholds (single source of truth) ──────────────────────────────────────
# Tunable; documented in CLAUDE.md's "Risky operations" list so changes go through review.
SAUDI_MIN_WAGE_MONTHLY_SAR: float = 4_000.0   # legal minimum for Saudi nationals
EXPAT_MIN_WAGE_MONTHLY_SAR: float = 1_000.0   # informal floor; below = likely a data error
ABSOLUTE_CEILING_MONTHLY_SAR: float = 500_000.0
STALE_MAX_YEARS: float = 5.0
OUTLIER_Z_THRESHOLD: float = 4.0              # within (family, level, region) cell, in log space
MIN_CONFIDENCE_TO_KEEP: float = 0.10
# 730 days (~2 years) keeps Mercer-tier survey data (initial confidence ~0.9) above
# floor for 4-5 years, and synthetic anchored data (initial 0.6) for ~2.5 years.
# Combined with STALE_MAX_YEARS=5 this caps usable age at 5 years regardless.
CONFIDENCE_HALF_LIFE_DAYS: float = 730.0
REQUIRED_COLUMNS: tuple[str, ...] = (
    "observed_at", "family", "level", "region", "sector", "ownership",
    "base_monthly", "is_saudi", "source",
)
DEDUP_KEY: tuple[str, ...] = (
    "source", "observed_at", "family", "level", "region", "sector",
    "ownership", "is_saudi", "base_monthly",
)


@dataclass(frozen=True)
class CleanupRule:
    """One rule's impact on the dataset."""

    name: str
    description: str
    rows_dropped: int
    rows_flagged: int = 0


@dataclass
class CleanupReport:
    rows_in: int
    rows_out: int
    rules: list[CleanupRule] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def rows_dropped(self) -> int:
        return self.rows_in - self.rows_out

    def to_dict(self) -> dict[str, object]:
        return {
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "rows_dropped": self.rows_dropped,
            "rules": [asdict(r) for r in self.rules],
            "notes": self.notes,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Cleanup report",
            "",
            f"- rows in:      `{self.rows_in}`",
            f"- rows out:     `{self.rows_out}`",
            f"- rows dropped: `{self.rows_dropped}` "
            f"({(self.rows_dropped / max(self.rows_in, 1) * 100):.1f}%)",
            "",
            "| rule | dropped | flagged | description |",
            "|---|---:|---:|---|",
        ]
        for r in self.rules:
            lines.append(
                f"| `{r.name}` | {r.rows_dropped} | {r.rows_flagged} | {r.description} |"
            )
        if self.notes:
            lines.extend(["", "## Notes", ""] + [f"- {n}" for n in self.notes])
        return "\n".join(lines) + "\n"


def _utc_timestamp(now: datetime) -> pd.Timestamp:
    """Return a UTC pd.Timestamp regardless of whether ``now`` is tz-aware."""
    ts = pd.Timestamp(now)
    return ts.tz_convert("UTC") if ts.tzinfo is not None else ts.tz_localize("UTC")


def _decay_confidence(df: pd.DataFrame, *, now: datetime) -> pd.Series:
    obs = pd.to_datetime(df["observed_at"], utc=True)
    days_old = (_utc_timestamp(now) - obs).dt.days.clip(lower=0)
    decay = np.power(0.5, days_old.to_numpy(dtype=float) / CONFIDENCE_HALF_LIFE_DAYS)
    base = df.get("confidence", pd.Series(np.ones(len(df)), index=df.index))
    return (base.astype(float).to_numpy() * decay).clip(0.0, 1.0)


def _segment_outlier_mask(df: pd.DataFrame) -> pd.Series:
    """Mark rows whose log(base) is > ``OUTLIER_Z_THRESHOLD`` sigma from segment mean."""
    if len(df) == 0:
        return pd.Series([], dtype=bool, index=df.index)
    work = df.copy()
    work["log_base"] = np.log(work["base_monthly"].astype(float).clip(lower=1.0))
    grp = work.groupby(["family", "level", "region"], dropna=False)["log_base"]
    mu = grp.transform("mean")
    sigma = grp.transform(lambda s: float(s.std(ddof=0)) if len(s) > 1 else 0.0)
    z = (work["log_base"] - mu) / sigma.replace(0.0, np.nan)
    return z.abs() > OUTLIER_Z_THRESHOLD


def clean_observations(
    raw: pd.DataFrame,
    *,
    now: datetime | None = None,
    drop_outliers: bool = False,
) -> tuple[pd.DataFrame, CleanupReport]:
    """Run the full cleanup pipeline.

    Args:
        raw: observations DataFrame matching the canonical schema.
        now: anchor for staleness + recency decay; defaults to UTC now.
        drop_outliers: if True, drop intra-segment outliers; otherwise just flag them
            via a new ``outlier_flag`` column. Default False — outliers may be real.

    Returns:
        ``(cleaned_df, report)``.
    """
    now = now or datetime.now(tz=UTC)
    df = raw.copy()
    report = CleanupReport(rows_in=len(df), rows_out=len(df))

    # 1. Required columns
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        msg = f"observations missing required columns: {missing_cols}"
        raise KeyError(msg)

    # 2. Drop rows with NaN in required fields
    before = len(df)
    df = df.dropna(subset=list(REQUIRED_COLUMNS))
    report.rules.append(CleanupRule(
        name="drop_missing_required",
        description=f"NaN in any of {REQUIRED_COLUMNS}",
        rows_dropped=before - len(df),
    ))

    # 3. Drop stale observations
    before = len(df)
    cutoff = _utc_timestamp(now) - timedelta(days=int(STALE_MAX_YEARS * 365.25))
    df = df.loc[pd.to_datetime(df["observed_at"], utc=True) >= cutoff]
    report.rules.append(CleanupRule(
        name="drop_stale",
        description=f"observed_at older than {STALE_MAX_YEARS} years",
        rows_dropped=before - len(df),
    ))

    # 4. Drop impossibly low wages (per nationality)
    before = len(df)
    floor = np.where(
        df["is_saudi"].astype(bool).to_numpy(),
        SAUDI_MIN_WAGE_MONTHLY_SAR,
        EXPAT_MIN_WAGE_MONTHLY_SAR,
    )
    df = df.loc[df["base_monthly"].astype(float).to_numpy() >= floor]
    report.rules.append(CleanupRule(
        name="drop_below_minimum_wage",
        description=(
            f"base_monthly < {SAUDI_MIN_WAGE_MONTHLY_SAR:.0f} for Saudis "
            f"or < {EXPAT_MIN_WAGE_MONTHLY_SAR:.0f} for non-Saudis"
        ),
        rows_dropped=before - len(df),
    ))

    # 5. Drop impossibly high wages
    before = len(df)
    df = df.loc[df["base_monthly"].astype(float) <= ABSOLUTE_CEILING_MONTHLY_SAR]
    report.rules.append(CleanupRule(
        name="drop_above_ceiling",
        description=f"base_monthly > {ABSOLUTE_CEILING_MONTHLY_SAR:.0f}",
        rows_dropped=before - len(df),
    ))

    # 6. Dedupe by composite key
    before = len(df)
    df = df.drop_duplicates(subset=list(DEDUP_KEY), keep="first").reset_index(drop=True)
    report.rules.append(CleanupRule(
        name="drop_duplicates",
        description=f"duplicate composite key {DEDUP_KEY}",
        rows_dropped=before - len(df),
    ))

    # 7. Decay confidence by recency
    df["confidence"] = _decay_confidence(df, now=now)
    before = len(df)
    df = df.loc[df["confidence"] >= MIN_CONFIDENCE_TO_KEEP].reset_index(drop=True)
    report.rules.append(CleanupRule(
        name="drop_low_confidence",
        description=f"confidence (after recency decay) < {MIN_CONFIDENCE_TO_KEEP}",
        rows_dropped=before - len(df),
    ))

    # 8. Intra-segment outliers
    outlier_mask = _segment_outlier_mask(df)
    n_outliers = int(outlier_mask.sum())
    if drop_outliers and n_outliers:
        df = df.loc[~outlier_mask].reset_index(drop=True)
        report.rules.append(CleanupRule(
            name="drop_segment_outliers",
            description=f"|z| > {OUTLIER_Z_THRESHOLD} on log(base) within (family, level, region)",
            rows_dropped=n_outliers,
        ))
    else:
        df["outlier_flag"] = outlier_mask.to_numpy()
        report.rules.append(CleanupRule(
            name="flag_segment_outliers",
            description=f"|z| > {OUTLIER_Z_THRESHOLD} on log(base) flagged but kept",
            rows_dropped=0,
            rows_flagged=n_outliers,
        ))

    report.rows_out = len(df)
    log.info("cleanup_done", **{r.name: r.rows_dropped for r in report.rules})
    return df, report


def write_report(report: CleanupReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "cleanup.md"
    json_path = out_dir / "cleanup.json"
    md_path.write_text(report.to_markdown(), encoding="utf-8")
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return md_path, json_path
