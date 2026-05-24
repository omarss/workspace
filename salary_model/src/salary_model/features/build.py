"""Feature engineering — leakage-safe transformations from canonical observations.

Each feature is anchored on ``observed_at``. Any rolling/lag join uses a strict
``ts <= observed_at - lag`` constraint so the model can never see the future. The
public entry point is :func:`build_feature_frame`, which returns a numeric matrix plus
the list of feature columns; categorical columns are integer-encoded by an in-frame
mapping so LightGBM can pick them up via ``categorical_feature=...``.

Two views are exposed:

* :func:`feature_columns_full` — used by the descriptive head.
* :func:`feature_columns_blind` — used by the recommendation head; excludes the
  sensitive set.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import numpy as np
import pandas as pd

from salary_model.data import anchors
from salary_model.data.types import EDUCATION_RANK, LEVEL_RANK, Education, Level

# ── Column inventories ───────────────────────────────────────────────────────

SENSITIVE_FEATURES: Final[tuple[str, ...]] = (
    "is_saudi", "gender_code", "age_bucket_ord",
)

CATEGORICAL_FEATURES: Final[tuple[str, ...]] = (
    "family_code", "level_code", "sector_code", "region_code", "ownership_code",
    "size_code", "employment_code", "workmode_code", "education_code",
)

NUMERIC_FEATURES: Final[tuple[str, ...]] = (
    "yoe", "yoe_sq", "level_rank", "education_rank",
    "region_base_multiplier", "sector_base_median", "ownership_lift",
    "family_premium", "size_lift", "log_sigma_sector",
    "month_sin", "month_cos", "year_ord", "vision_phase",
    # Macro: joined per-row at `observed_at` from the monthly macro series
    "cpi_yoy", "cpi_yoy_lag3", "cpi_yoy_lag12",
    "policy_rate", "policy_rate_lag3",
    "brent_usd", "brent_3m_avg_usd", "brent_yoy",
    "is_metro", "is_pif_or_mnc", "is_exec",
)


def feature_columns_full() -> list[str]:
    """Columns visible to the descriptive head (sensitive included)."""
    return list(CATEGORICAL_FEATURES) + list(NUMERIC_FEATURES) + list(SENSITIVE_FEATURES)


def feature_columns_blind() -> list[str]:
    """Columns visible to the recommendation head (sensitive excluded)."""
    return list(CATEGORICAL_FEATURES) + list(NUMERIC_FEATURES)


@dataclass(frozen=True)
class BuiltFeatures:
    X: pd.DataFrame
    y_base: pd.Series
    y_tcc: pd.Series
    weights: pd.Series
    sensitive: pd.DataFrame
    columns_full: list[str]
    columns_blind: list[str]
    categorical: list[str]
    # Maps "<source_column>_code" -> {raw_value: integer_code}. Persisted with the model
    # bundle so the API can encode incoming raw values to the codes the model was
    # trained against. Unknown values map to -1 (LightGBM treats this as missing).
    category_codes: dict[str, dict[str, int]]


# ── Helpers ──────────────────────────────────────────────────────────────────

_AGE_BUCKET_ORDER: Final[tuple[str, ...]] = (
    "20-24", "25-29", "30-34", "35-39", "40-44", "45-49", "50-54", "55-64",
)


def _ordinal_categorical(series: pd.Series, ordering: tuple[str, ...]) -> pd.Series:
    mapping = {v: i for i, v in enumerate(ordering)}
    return series.map(mapping).astype("Int16")


def _to_codes(series: pd.Series) -> tuple[pd.Series, dict[str, int]]:
    """Convert a categorical/string column to integer codes; also returns the mapping."""
    cat = series.astype("category")
    mapping: dict[str, int] = {str(v): int(i) for i, v in enumerate(cat.cat.categories)}
    return cat.cat.codes.astype("int32"), mapping


def _vision_phase(year: int) -> int:
    if year < 2018:
        return 0
    if year < 2022:
        return 1
    if year < 2026:
        return 2
    return 3


# ── Public entrypoint ────────────────────────────────────────────────────────


def build_feature_frame(observations: pd.DataFrame) -> BuiltFeatures:
    """Build the feature matrix from canonical observations.

    Args:
        observations: dataframe as produced by ``data.synthetic.generate`` /
            ``data.build.load_latest_snapshot``.

    Returns:
        :class:`BuiltFeatures` with consistent column ordering.
    """
    df = observations.copy()
    if "observed_at" not in df.columns:
        msg = "observations must contain 'observed_at'"
        raise KeyError(msg)
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)

    # ── Individual & job ──────────────────────────────────────────────────────
    df["yoe_sq"] = df["yoe"].astype(float) ** 2
    df["level_rank"] = df["level"].map(
        {lvl.value: rank for lvl, rank in LEVEL_RANK.items()}
    ).astype("Int16")
    df["education_rank"] = df["education"].map(
        {edu.value: rank for edu, rank in EDUCATION_RANK.items()}
    ).astype("Int16")

    # ── Static lookups from anchor tables ─────────────────────────────────────
    df["region_base_multiplier"] = df["region"].map(
        {r.value: v for r, v in anchors.REGION_BASE_MULTIPLIER.items()}
    ).astype(float)
    df["sector_base_median"] = df["sector"].map(
        {s.value: v for s, v in anchors.SECTOR_BASE_MEDIAN.items()}
    ).astype(float)
    df["ownership_lift"] = df["ownership"].map(
        {o.value: v for o, v in anchors.OWNERSHIP_LIFT.items()}
    ).astype(float)
    df["family_premium"] = df["family"].map(
        {f.value: v for f, v in anchors.FAMILY_PREMIUM.items()}
    ).astype(float)
    df["size_lift"] = df["size_bucket"].map(anchors.SIZE_LIFT).astype(float)
    df["log_sigma_sector"] = df["sector"].map(
        {s.value: v for s, v in anchors.SECTOR_LOG_SIGMA.items()}
    ).astype(float)

    # ── Time ──────────────────────────────────────────────────────────────────
    months = df["observed_at"].dt.month.astype(float)
    df["month_sin"] = np.sin(2.0 * np.pi * months / 12.0)
    df["month_cos"] = np.cos(2.0 * np.pi * months / 12.0)
    df["year_ord"] = df["observed_at"].dt.year.astype(int)
    df["vision_phase"] = df["year_ord"].map(_vision_phase).astype("Int8")

    # ── Macro: time-varying join via merge_asof on observed_at ────────────────
    # Falls back to the bundled monthly series if no snapshot is on disk yet.
    from salary_model.data.build import load_latest_macro_series  # local import to avoid cycle
    macro = load_latest_macro_series().sort_values("month")
    macro_cols = [
        "cpi_yoy", "cpi_yoy_lag1", "cpi_yoy_lag3", "cpi_yoy_lag6", "cpi_yoy_lag12",
        "policy_rate", "policy_rate_lag1", "policy_rate_lag3",
        "policy_rate_lag6", "policy_rate_lag12",
        "brent_usd", "brent_3m_avg_usd", "brent_yoy", "sar_to_usd",
    ]
    df = df.sort_values("observed_at").reset_index(drop=False)
    df = pd.merge_asof(
        df, macro[["month", *macro_cols]],
        left_on="observed_at", right_on="month",
        direction="backward",
    )
    df = df.drop(columns=["month"]).set_index("index").sort_index()
    df.index.name = None
    # Any rows older than the macro series get the earliest snapshot via forward fill
    for col in macro_cols:
        if col in df.columns:
            df[col] = df[col].astype(float).bfill().ffill().fillna(0.0)

    # ── Flags ─────────────────────────────────────────────────────────────────
    df["is_metro"] = df["region"].isin(("RUH", "JED", "EST")).astype("int8")
    df["is_pif_or_mnc"] = df["ownership"].isin(("pif_backed", "mnc")).astype("int8")
    df["is_exec"] = df["level"].isin(
        ("M3", "M4", "M5", "D1", "D2", "D3", "VP", "SVP", "CXO")
    ).astype("int8")

    # ── Sensitive (gated; preserved for descriptive head + audit) ─────────────
    df["gender_code"] = (df["gender"] == "F").astype("int8")
    df["age_bucket_ord"] = _ordinal_categorical(df["age_bucket"], _AGE_BUCKET_ORDER)
    df["is_saudi"] = df["is_saudi"].astype("int8")

    # ── Categorical encoding ──────────────────────────────────────────────────
    category_codes: dict[str, dict[str, int]] = {}
    for code_col, src_col in (
        ("family_code", "family"),
        ("level_code", "level"),
        ("sector_code", "sector"),
        ("region_code", "region"),
        ("ownership_code", "ownership"),
        ("size_code", "size_bucket"),
        ("employment_code", "employment_type"),
        ("workmode_code", "work_mode"),
        ("education_code", "education"),
    ):
        codes, mapping = _to_codes(df[src_col])
        df[code_col] = codes
        category_codes[code_col] = mapping

    columns_full = feature_columns_full()
    columns_blind = feature_columns_blind()
    categorical = list(CATEGORICAL_FEATURES)

    X = df[columns_full].copy()
    y_base = df["base_monthly"].astype(float)
    y_tcc_raw = df.get("tcc_monthly") if "tcc_monthly" in df.columns else _derive_tcc(df)
    y_tcc = y_tcc_raw.astype(float)
    default_w = pd.Series(np.ones(len(df)), index=df.index)
    weights = df.get("confidence", default_w).astype(float)
    sensitive = df[["gender", "is_saudi", "age_bucket"]].copy()

    return BuiltFeatures(
        X=X,
        y_base=y_base,
        y_tcc=y_tcc,
        weights=weights,
        sensitive=sensitive,
        columns_full=columns_full,
        columns_blind=columns_blind,
        categorical=categorical,
        category_codes=category_codes,
    )


def _derive_tcc(df: pd.DataFrame) -> pd.Series:
    return (
        df["base_monthly"]
        + df["housing_monthly"]
        + df["transport_monthly"]
        + df["other_fixed_monthly"]
        + df["variable_monthly_eq"]
        + df["equity_annual_ev"] / 12.0
    )


def temporal_split(
    observations: pd.DataFrame,
    *,
    val_fraction: float,
    test_fraction: float,
) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex, pd.DatetimeIndex, datetime, datetime]:
    """Compute temporal split timestamps and return masks as DatetimeIndex.

    Returns ``(train_mask, val_mask, test_mask, t_val, t_test)`` where masks are the
    *observation indices* belonging to each split, sorted by ``observed_at``.
    """
    ts = pd.to_datetime(observations["observed_at"], utc=True).sort_values()
    n = len(ts)
    n_test = int(n * test_fraction)
    n_val = int(n * val_fraction)
    t_test = ts.iloc[n - n_test]
    t_val = ts.iloc[n - n_test - n_val]
    obs_ts = pd.to_datetime(observations["observed_at"], utc=True)
    train_idx = observations.index[obs_ts < t_val]
    val_idx = observations.index[(obs_ts >= t_val) & (obs_ts < t_test)]
    test_idx = observations.index[obs_ts >= t_test]
    return (
        pd.DatetimeIndex(observations.loc[train_idx, "observed_at"]),
        pd.DatetimeIndex(observations.loc[val_idx, "observed_at"]),
        pd.DatetimeIndex(observations.loc[test_idx, "observed_at"]),
        t_val.to_pydatetime().replace(tzinfo=UTC),
        t_test.to_pydatetime().replace(tzinfo=UTC),
    )


def split_indices(
    observations: pd.DataFrame,
    *,
    val_fraction: float,
    test_fraction: float,
) -> tuple[pd.Index, pd.Index, pd.Index]:
    """Return integer-locating Indices for train/val/test sorted by observed_at."""
    obs_ts = pd.to_datetime(observations["observed_at"], utc=True)
    order = obs_ts.sort_values().index
    n = len(order)
    n_test = int(n * test_fraction)
    n_val = int(n * val_fraction)
    train_idx = order[: n - n_val - n_test]
    val_idx = order[n - n_val - n_test : n - n_test]
    test_idx = order[n - n_test :]
    return train_idx, val_idx, test_idx


__all__ = [
    "CATEGORICAL_FEATURES",
    "NUMERIC_FEATURES",
    "SENSITIVE_FEATURES",
    "BuiltFeatures",
    "build_feature_frame",
    "feature_columns_blind",
    "feature_columns_full",
    "split_indices",
    "temporal_split",
]


_ = Education, Level  # silence ruff for re-export of types via TYPE_CHECKING patterns
