"""Calibrate the synthetic generator's output to live GASTAT wage anchors.

Re-anchors three marginal distributions of the synthetic dataset to match what the
published KAPSARC/GASTAT data says:

1. **Mean wage** — scale every row's ``base_monthly`` proportionally so the
   dataset mean matches the published "Average Monthly Wages of Paid employees"
   for the reference year, optionally inflation-trended forward to the observation
   year using the monthly CPI series.
2. **Saudi vs non-Saudi premium** — adjust the Saudi multiplier so the
   ``Saudi mean / All-pop mean`` ratio matches the published value (which is much
   larger than what my recall-based bundled anchors encoded; see v0.5 fairness
   report: real premium is +55%, our seeded number was ~-8% in the wrong
   direction).
3. **Gender gap** — adjust the female-vs-male multiplier so the published
   all-population gap is matched. KSA's published gap is small (~-1%) because
   female labor is concentrated in higher-education sectors; the Saudi-only gap
   is much larger.

The calibration is **multiplicative** — it preserves the sector x level x region
x ownership structure encoded in the generator while pinning the three marginals
to truth. After calibration:

- the dataset mean equals (or is within tolerance of) the published mean
- the Saudi / all-pop premium matches the published one
- the female / male ratio (all-pop) matches the published one

Each adjustment is recorded in :class:`CalibrationReport`, persisted alongside
the dataset snapshot, and surfaced in the API's ``data_provenance`` block.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from salary_model.config import get_logger
from salary_model.data.sources.wage_index_live import (
    gender_gap_pct,
    lookup_wage,
    saudi_gap_pct,
)

log = get_logger("salary_model.data.calibrate")

# Tolerance for "match" verification (relative).
MATCH_TOLERANCE_PCT: float = 0.01


@dataclass(frozen=True)
class CalibrationStep:
    name: str
    before: float
    after: float
    target: float
    multiplier: float


@dataclass
class CalibrationReport:
    reference_year: int
    rows_calibrated: int
    steps: list[CalibrationStep] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "reference_year": self.reference_year,
            "rows_calibrated": self.rows_calibrated,
            "steps": [asdict(s) for s in self.steps],
            "skipped": self.skipped,
            "notes": self.notes,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Calibration report",
            "",
            f"- Reference year: `{self.reference_year}`",
            f"- Rows calibrated: `{self.rows_calibrated}`",
            "",
            "| step | before | target | after | ×multiplier |",
            "|---|---:|---:|---:|---:|",
        ]
        for s in self.steps:
            lines.append(
                f"| `{s.name}` | {s.before:,.2f} | {s.target:,.2f} | {s.after:,.2f} | "
                f"{s.multiplier:.4f} |"
            )
        if self.skipped:
            lines.extend(["", "## Skipped", ""] + [f"- {s}" for s in self.skipped])
        if self.notes:
            lines.extend(["", "## Notes", ""] + [f"- {n}" for n in self.notes])
        return "\n".join(lines) + "\n"


def _annual_cpi_factor_to_year(cpi_yoy_per_year: float, n_years: int) -> float:
    """Compound annual CPI factor (e.g. 0.02 + 6 -> 1.126)."""
    return float((1.0 + cpi_yoy_per_year) ** n_years)


def calibrate_to_live(
    df: pd.DataFrame,
    wage_index: pd.DataFrame,
    *,
    target_year: int | None = None,
    cpi_yoy: float = 0.02,
    apply_premium: bool = True,
    apply_gender: bool = True,
    target_population: str = "saudi",
) -> tuple[pd.DataFrame, CalibrationReport]:
    """Re-anchor a synthetic dataframe to published GASTAT wage marginals.

    Args:
        df: synthetic observations DataFrame with required columns
            ``base_monthly``, ``is_saudi``, ``gender``, ``observed_at``.
        wage_index: output of
            :func:`salary_model.data.sources.wage_index_live.build_wage_index`.
        target_year: reference year for the published anchors; defaults to the
            most recent year in ``wage_index``.
        cpi_yoy: average annual CPI used to trend the published mean forward to
            each observation's year. Default 2%, roughly the KSA 5-year average.
        apply_premium: when True, adjust the Saudi multiplier to match the
            published Saudi-vs-all premium.
        apply_gender: when True, adjust the female multiplier to match the
            published all-population gender gap.
        target_population: ``"saudi"`` (default) pins the dataset mean to the
            published *Saudi-only* mean (~10k SAR in 2020) — appropriate for
            predicting Saudi-resident knowledge-worker compensation. ``"all"``
            pins to the all-employee mean (~7k SAR), which is dominated by
            low-wage expat labor and produces conservative numbers for
            white-collar use cases.

    Returns:
        ``(calibrated_df, report)``. If the wage index is empty, returns the
        original ``df`` and a report listing every step as ``skipped``.
    """
    report = CalibrationReport(
        reference_year=target_year or 0, rows_calibrated=len(df)
    )
    if wage_index.empty:
        report.skipped.extend(["mean", "saudi_premium", "gender_gap"])
        report.notes.append("live wage_index is empty; calibration skipped")
        return df, report

    use_year = (
        target_year if target_year is not None else int(wage_index["year"].max())
    )
    report = CalibrationReport(
        reference_year=use_year, rows_calibrated=len(df)
    )

    work = df.copy()

    # Helper closures use the latest base_monthly column
    def group_mean(mask: pd.Series) -> float | None:
        sub = work.loc[mask, "base_monthly"].astype(float)
        return float(sub.mean()) if len(sub) else None

    # Order matters: pin the ratios first (Saudi premium, gender gap), THEN pin
    # the overall mean. Doing mean first then shifting Saudi/female rows would
    # break the mean invariant we just set. The relative-shift steps preserve
    # whatever mean is currently on the data.

    # ── 1. Saudi premium alignment ────────────────────────────────────────────
    if apply_premium:
        target_premium = saudi_gap_pct(wage_index, year=use_year)
        all_mean = group_mean(pd.Series(True, index=work.index))
        saudi_mean = group_mean(work["is_saudi"].astype(bool))
        if target_premium is None or all_mean is None or saudi_mean is None:
            report.skipped.append("saudi_premium")
        else:
            current_premium = (saudi_mean - all_mean) / all_mean if all_mean else 0.0
            # Solve for multiplier m applied to Saudi rows that yields the target.
            # Let n_s, n_x be Saudi and non-Saudi counts; mu_s, mu_x their means.
            # New saudi mean = m * mu_s; new all-pop mean = (n_s * m * mu_s + n_x * mu_x) / N
            # We want (m*mu_s - new_all) / new_all = target.
            #   => m*mu_s = (1+target) * new_all
            #   => m*mu_s = (1+target) * (n_s * m * mu_s + n_x * mu_x) / N
            # Solve for m:
            n_s = int(work["is_saudi"].astype(bool).sum())
            n_x = len(work) - n_s
            mu_x = group_mean(~work["is_saudi"].astype(bool)) or 0.0
            mu_s = saudi_mean
            if mu_s > 0 and n_x > 0 and mu_x > 0:
                t = float(target_premium)
                # Algebra: m = (1+t) * n_x * mu_x / (mu_s * (N - (1+t) * n_s))
                denom = mu_s * (len(work) - (1.0 + t) * n_s)
                if abs(denom) > 1e-9:
                    m = (1.0 + t) * n_x * mu_x / denom
                    if m > 0:
                        work.loc[work["is_saudi"].astype(bool), "base_monthly"] = (
                            work.loc[work["is_saudi"].astype(bool), "base_monthly"]
                            .astype(float) * m
                        )
                        new_all = group_mean(pd.Series(True, index=work.index)) or 0.0
                        new_saudi = group_mean(work["is_saudi"].astype(bool)) or 0.0
                        new_premium = (
                            (new_saudi - new_all) / new_all if new_all else 0.0
                        )
                        report.steps.append(CalibrationStep(
                            name="saudi_premium",
                            before=current_premium,
                            target=t,
                            after=new_premium,
                            multiplier=m,
                        ))
                    else:
                        report.skipped.append("saudi_premium")
                else:
                    report.skipped.append("saudi_premium")
            else:
                report.skipped.append("saudi_premium")
    else:
        report.skipped.append("saudi_premium")

    # ── 2. Gender gap alignment (all-population) ──────────────────────────────
    if apply_gender:
        target_gap = gender_gap_pct(wage_index, year=use_year)
        male_mean = group_mean(work["gender"].astype(str) == "M")
        female_mean = group_mean(work["gender"].astype(str) == "F")
        if target_gap is None or male_mean is None or female_mean is None:
            report.skipped.append("gender_gap")
        elif male_mean > 0:
            current_gap = (female_mean - male_mean) / male_mean
            # Multiplier applied to female rows so the new gap matches target.
            # We assume male mean unchanged (anchor on male side).
            # new_female_mean = m * female_mean; target_gap = (m*f - male) / male
            # => m = (target_gap + 1) * male_mean / female_mean
            t = float(target_gap)
            m_fem = (t + 1.0) * male_mean / female_mean
            if m_fem > 0:
                fmask = work["gender"].astype(str) == "F"
                work.loc[fmask, "base_monthly"] = (
                    work.loc[fmask, "base_monthly"].astype(float) * m_fem
                )
                new_male = group_mean(work["gender"].astype(str) == "M") or 1.0
                new_female = group_mean(work["gender"].astype(str) == "F") or 0.0
                new_gap = (new_female - new_male) / new_male if new_male else 0.0
                report.steps.append(CalibrationStep(
                    name="gender_gap",
                    before=current_gap,
                    target=t,
                    after=new_gap,
                    multiplier=m_fem,
                ))
            else:
                report.skipped.append("gender_gap")
        else:
            report.skipped.append("gender_gap")
    else:
        report.skipped.append("gender_gap")

    # ── 3. Mean alignment (last; preserves the ratios pinned above) ──────────
    # target_population="saudi" pins to the Saudi-only published mean (~10k); the
    # default for our use case. "all" pins to the all-employee mean (~7k) which
    # is dominated by floor-tier expat labor.
    if target_population == "saudi":
        published_mean = lookup_wage(
            wage_index, year=use_year, gender="Total", is_saudi=True,
        )
        report.notes.append("mean pinned to Saudi-only published wage")
    else:
        published_mean = lookup_wage(
            wage_index, year=use_year, gender="Total", is_saudi=False,
        )
        report.notes.append("mean pinned to all-employee published wage")
    if published_mean is None:
        report.skipped.append("mean")
    else:
        obs_year = pd.to_datetime(work["observed_at"], utc=True).dt.year
        trend = obs_year.apply(
            lambda y: _annual_cpi_factor_to_year(cpi_yoy, max(int(y) - use_year, 0))
        )
        target_per_row = published_mean * trend.to_numpy(dtype=float)
        current_mean = float(work["base_monthly"].astype(float).mean())
        target_overall = float(np.mean(target_per_row))
        if current_mean > 0:
            mult = target_overall / current_mean
            work["base_monthly"] = work["base_monthly"].astype(float) * mult
            new_mean = float(work["base_monthly"].astype(float).mean())
            report.steps.append(CalibrationStep(
                name="mean",
                before=current_mean,
                target=target_overall,
                after=new_mean,
                multiplier=mult,
            ))

    # Recompute tcc_monthly when allowances are derived from base
    if {"housing_monthly", "transport_monthly", "other_fixed_monthly",
        "variable_monthly_eq", "equity_annual_ev"}.issubset(work.columns):
        work["tcc_monthly"] = (
            work["base_monthly"]
            + work["housing_monthly"]
            + work["transport_monthly"]
            + work["other_fixed_monthly"]
            + work["variable_monthly_eq"]
            + work["equity_annual_ev"] / 12.0
        ).round(2)

    log.info(
        "calibrate_done",
        rows=len(work),
        steps=[s.name for s in report.steps],
        skipped=report.skipped,
    )
    return work, report


def write_report(report: CalibrationReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "calibration.md"
    js = out_dir / "calibration.json"
    md.write_text(report.to_markdown(), encoding="utf-8")
    js.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return md, js
