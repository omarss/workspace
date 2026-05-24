"""Anchored synthetic observation generator.

Generates individual-level salary observations whose marginal and conditional
distributions match published GASTAT / SAMA aggregates. Every record is tagged
``source = "synthetic_anchored"`` and capped at ``confidence = 0.6`` so downstream code
can never confuse it with authoritative microdata.

The structure encodes Saudi-specific dynamics:
- Riyadh / Eastern / Jeddah regional premia
- PIF-backed and MNC lift
- Saudization (Nitaqat) penetration by sector
- Realistic gender share by family
- A descriptive gender gap (so the fairness layer has something to detect)
- Sector-specific log-normal heteroscedasticity
- Time variation: monthly inflation drift plus a Vision-2030 phase shift

Generator is deterministic given ``seed``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import exp
from typing import Final

import numpy as np
import pandas as pd

from salary_model.data import anchors
from salary_model.data.types import (
    Education,
    EmploymentType,
    Gender,
    JobFamily,
    Level,
    Ownership,
    Region,
    Sector,
    WorkMode,
)


@dataclass(frozen=True)
class SynthSpec:
    """Configuration knobs for the synthetic generator. Public so tests can shrink it."""

    n_rows: int
    seed: int
    start_date: datetime
    end_date: datetime
    base_year: int = 2024
    monthly_inflation: float = 0.0017  # ~2% annual, applied multiplicatively
    vision_phase_lift: float = 0.04    # cumulative lift entering phase_3 (2026+)
    contractor_share: float = 0.05
    remote_share: float = 0.10
    hybrid_share: float = 0.25


_FAMILY_TO_SECTOR_BIAS: Final[dict[JobFamily, Sequence[tuple[Sector, float]]]] = {
    JobFamily.SWE: (
        (Sector.ICT, 0.55), (Sector.FINANCE, 0.15), (Sector.TELECOM, 0.10),
        (Sector.PROFESSIONAL, 0.10), (Sector.MANUFACTURING, 0.05), (Sector.OIL_GAS, 0.05),
    ),
    JobFamily.DATA: (
        (Sector.ICT, 0.40), (Sector.FINANCE, 0.30), (Sector.TELECOM, 0.10),
        (Sector.HEALTH, 0.05), (Sector.PROFESSIONAL, 0.10), (Sector.OIL_GAS, 0.05),
    ),
    JobFamily.PM: (
        (Sector.ICT, 0.40), (Sector.FINANCE, 0.20), (Sector.TELECOM, 0.15),
        (Sector.PROFESSIONAL, 0.15), (Sector.MANUFACTURING, 0.10),
    ),
    JobFamily.DESIGN: (
        (Sector.ICT, 0.45), (Sector.PROFESSIONAL, 0.35),
        (Sector.FINANCE, 0.10), (Sector.WHOLESALE_RETAIL, 0.10),
    ),
    JobFamily.SALES: (
        (Sector.WHOLESALE_RETAIL, 0.30), (Sector.FINANCE, 0.20), (Sector.TELECOM, 0.10),
        (Sector.ICT, 0.15), (Sector.PROFESSIONAL, 0.10), (Sector.MANUFACTURING, 0.10),
        (Sector.HOSPITALITY, 0.05),
    ),
    JobFamily.MARKETING: (
        (Sector.WHOLESALE_RETAIL, 0.25), (Sector.PROFESSIONAL, 0.20), (Sector.ICT, 0.20),
        (Sector.FINANCE, 0.15), (Sector.HOSPITALITY, 0.10), (Sector.TELECOM, 0.10),
    ),
    JobFamily.FIN: (
        (Sector.FINANCE, 0.45), (Sector.GOVERNMENT, 0.15), (Sector.OIL_GAS, 0.10),
        (Sector.PROFESSIONAL, 0.10), (Sector.MANUFACTURING, 0.10),
        (Sector.WHOLESALE_RETAIL, 0.10),
    ),
    JobFamily.HR: (
        (Sector.PROFESSIONAL, 0.25), (Sector.GOVERNMENT, 0.20), (Sector.FINANCE, 0.15),
        (Sector.MANUFACTURING, 0.10), (Sector.HEALTH, 0.10), (Sector.ICT, 0.10),
        (Sector.WHOLESALE_RETAIL, 0.10),
    ),
    JobFamily.OPS: (
        (Sector.MANUFACTURING, 0.30), (Sector.TRANSPORT, 0.20), (Sector.OIL_GAS, 0.15),
        (Sector.UTILITIES, 0.10), (Sector.WHOLESALE_RETAIL, 0.10),
        (Sector.PROFESSIONAL, 0.15),
    ),
    JobFamily.LEGAL: (
        (Sector.PROFESSIONAL, 0.40), (Sector.GOVERNMENT, 0.25), (Sector.FINANCE, 0.20),
        (Sector.OIL_GAS, 0.05), (Sector.ICT, 0.10),
    ),
    JobFamily.CUSTOMER: (
        (Sector.WHOLESALE_RETAIL, 0.35), (Sector.TELECOM, 0.20), (Sector.FINANCE, 0.15),
        (Sector.ICT, 0.10), (Sector.HOSPITALITY, 0.20),
    ),
    JobFamily.SUPPLY: (
        (Sector.MANUFACTURING, 0.30), (Sector.TRANSPORT, 0.25), (Sector.WHOLESALE_RETAIL, 0.20),
        (Sector.OIL_GAS, 0.15), (Sector.CONSTRUCTION, 0.10),
    ),
    JobFamily.ENG_MECH: (
        (Sector.MANUFACTURING, 0.40), (Sector.OIL_GAS, 0.30), (Sector.UTILITIES, 0.10),
        (Sector.CONSTRUCTION, 0.10), (Sector.TRANSPORT, 0.10),
    ),
    JobFamily.ENG_CIVIL: (
        (Sector.CONSTRUCTION, 0.50), (Sector.REAL_ESTATE, 0.20), (Sector.GOVERNMENT, 0.15),
        (Sector.UTILITIES, 0.10), (Sector.OIL_GAS, 0.05),
    ),
    JobFamily.ENG_ELEC: (
        (Sector.UTILITIES, 0.30), (Sector.MANUFACTURING, 0.25), (Sector.OIL_GAS, 0.20),
        (Sector.CONSTRUCTION, 0.15), (Sector.TELECOM, 0.10),
    ),
    JobFamily.HEALTH: (
        (Sector.HEALTH, 0.95), (Sector.GOVERNMENT, 0.05),
    ),
    JobFamily.EDU: (
        (Sector.EDUCATION, 0.95), (Sector.GOVERNMENT, 0.05),
    ),
}

_LEVEL_BY_YOE: Final[Sequence[tuple[tuple[float, float], Sequence[tuple[Level, float]]]]] = (
    ((0, 1.5),  ((Level.IC1, 0.85), (Level.IC2, 0.15))),
    ((1.5, 3),  ((Level.IC2, 0.75), (Level.IC3, 0.25))),
    ((3, 6),    ((Level.IC3, 0.55), (Level.IC4, 0.30), (Level.M1, 0.10), (Level.IC2, 0.05))),
    ((6, 10),   ((Level.IC4, 0.45), (Level.IC5, 0.20), (Level.M1, 0.20),
                 (Level.M2, 0.10), (Level.IC3, 0.05))),
    ((10, 14),  ((Level.IC5, 0.30), (Level.M2, 0.25), (Level.M3, 0.20),
                 (Level.IC4, 0.15), (Level.IC6, 0.10))),
    ((14, 18),  ((Level.M3, 0.30), (Level.IC6, 0.20), (Level.M4, 0.15),
                 (Level.D1, 0.15), (Level.IC5, 0.20))),
    ((18, 25),  ((Level.M4, 0.25), (Level.D1, 0.20), (Level.IC6, 0.15),
                 (Level.D2, 0.15), (Level.M5, 0.10), (Level.VP, 0.15))),
    ((25, 60),  ((Level.D2, 0.25), (Level.D3, 0.20), (Level.VP, 0.20),
                 (Level.SVP, 0.15), (Level.M5, 0.10), (Level.CXO, 0.10))),
)

_REGION_WEIGHTS: Final[dict[Region, float]] = {
    Region.RIYADH: 0.38, Region.EASTERN: 0.18, Region.JEDDAH: 0.13,
    Region.MAKKAH: 0.06, Region.MADINAH: 0.04, Region.QASSIM: 0.04,
    Region.TABUK: 0.04, Region.HAIL: 0.02, Region.ASIR: 0.04,
    Region.JAZAN: 0.03, Region.NAJRAN: 0.02, Region.BAHA: 0.01,
    Region.NORTHERN_BORDERS: 0.01,
}

_OWNERSHIP_WEIGHTS: Final[dict[Ownership, float]] = {
    Ownership.PRIVATE: 0.42, Ownership.SEMIGOV: 0.15, Ownership.PIF_BACKED: 0.08,
    Ownership.MNC: 0.10, Ownership.STARTUP: 0.05, Ownership.PUBLIC: 0.20,
}

_SIZE_WEIGHTS: Final[Sequence[tuple[str, float]]] = (
    ("1-9", 0.10), ("10-49", 0.18), ("50-249", 0.25),
    ("250-999", 0.25), ("1000+", 0.22),
)

_EDU_WEIGHTS: Final[Sequence[tuple[Education, float]]] = (
    (Education.HIGH_SCHOOL, 0.10),
    (Education.DIPLOMA, 0.20),
    (Education.BACHELORS, 0.55),
    (Education.MASTERS, 0.13),
    (Education.PHD, 0.02),
)

_AGE_BUCKETS: Final[Sequence[str]] = (
    "20-24", "25-29", "30-34", "35-39", "40-44", "45-49", "50-54", "55-64",
)


def _choice(rng: np.random.Generator, items: Sequence[tuple[object, float]]) -> object:
    keys = [k for k, _ in items]
    weights = np.array([w for _, w in items], dtype=float)
    weights = weights / weights.sum()
    idx = int(rng.choice(len(keys), p=weights))
    return keys[idx]


def _pick_level(rng: np.random.Generator, yoe: float) -> Level:
    for (lo, hi), choices in _LEVEL_BY_YOE:
        if lo <= yoe < hi:
            return Level(_choice(rng, choices))
    return Level.IC4


def _pick_sector(rng: np.random.Generator, family: JobFamily) -> Sector:
    return Sector(_choice(rng, _FAMILY_TO_SECTOR_BIAS[family]))


def _pick_age(rng: np.random.Generator, yoe: float) -> str:
    # rough mapping yoe -> typical age cohort
    base = 22 + int(yoe) + int(rng.integers(-2, 3))
    if base < 25:
        return "20-24"
    if base < 30:
        return "25-29"
    if base < 35:
        return "30-34"
    if base < 40:
        return "35-39"
    if base < 45:
        return "40-44"
    if base < 50:
        return "45-49"
    if base < 55:
        return "50-54"
    return "55-64"


def _stable_company_id(rng: np.random.Generator, sector: Sector, region: Region) -> str:
    raw = f"{sector.value}-{region.value}-{int(rng.integers(0, 4000))}"
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"C{digest}"


def _yoe_draw(rng: np.random.Generator) -> float:
    # right-skewed labor distribution; capped at 40
    val = float(rng.gamma(shape=2.1, scale=4.0))
    return float(min(max(val, 0.0), 40.0))


def _time_lift(observed_at: datetime, spec: SynthSpec) -> float:
    months_from_base = (observed_at.year - spec.base_year) * 12 + observed_at.month - 1
    lift = (1.0 + spec.monthly_inflation) ** months_from_base
    if observed_at.year >= 2026:
        lift *= 1.0 + spec.vision_phase_lift
    return lift


def _draw_observed_at(rng: np.random.Generator, spec: SynthSpec) -> datetime:
    span_seconds = int((spec.end_date - spec.start_date).total_seconds())
    delta = int(rng.integers(0, span_seconds))
    return spec.start_date + timedelta(seconds=delta)


def generate(spec: SynthSpec) -> pd.DataFrame:
    """Generate ``spec.n_rows`` anchored synthetic salary observations."""
    rng = np.random.default_rng(spec.seed)

    records: list[dict[str, object]] = []
    families = list(JobFamily)
    families_w = np.array([
        0.10,  # SWE
        0.05,  # DATA
        0.04,  # PM
        0.03,  # DESIGN
        0.10,  # SALES
        0.05,  # MARKETING
        0.07,  # FIN
        0.04,  # HR
        0.07,  # OPS
        0.02,  # LEGAL
        0.06,  # CUSTOMER
        0.04,  # SUPPLY
        0.05,  # ENG_MECH
        0.05,  # ENG_CIVIL
        0.05,  # ENG_ELEC
        0.10,  # HEALTH
        0.08,  # EDU
    ])
    families_w = families_w / families_w.sum()

    for i in range(spec.n_rows):
        family = JobFamily(rng.choice(families, p=families_w))
        sector = _pick_sector(rng, family)

        region = Region(_choice(rng, list(_REGION_WEIGHTS.items())))
        ownership = Ownership(_choice(rng, list(_OWNERSHIP_WEIGHTS.items())))
        if sector == Sector.GOVERNMENT:
            ownership = Ownership.PUBLIC
        size_bucket = str(_choice(rng, list(_SIZE_WEIGHTS)))
        education = Education(_choice(rng, list(_EDU_WEIGHTS)))
        yoe = _yoe_draw(rng)
        level = _pick_level(rng, yoe)
        age_bucket = _pick_age(rng, yoe)

        # gender / nationality, anchored to public shares
        female_share = anchors.gender_share_anchor(family)
        gender = Gender.FEMALE if rng.random() < female_share else Gender.MALE
        saudi_share = anchors.saudi_share_anchor(sector)
        is_saudi = bool(rng.random() < saudi_share)

        # employment mode
        u = rng.random()
        employment_type = EmploymentType.CONTRACT if u < spec.contractor_share else (
            EmploymentType.INTERN if level == Level.IC1 and rng.random() < 0.4
            else EmploymentType.FULL_TIME
        )
        v = rng.random()
        work_mode = (
            WorkMode.REMOTE if v < spec.remote_share
            else WorkMode.HYBRID if v < spec.remote_share + spec.hybrid_share
            else WorkMode.ONSITE
        )

        observed_at = _draw_observed_at(rng, spec)

        # compute anchored base salary
        sector_med = anchors.SECTOR_BASE_MEDIAN[sector]
        region_mult = anchors.REGION_BASE_MULTIPLIER[region]
        ownership_lift = anchors.OWNERSHIP_LIFT[ownership]
        family_lift = anchors.FAMILY_PREMIUM[family]
        level_mult = anchors.LEVEL_MULTIPLIER[level]
        education_premium = anchors.EDUCATION_PREMIUM[education]
        size_lift = anchors.SIZE_LIFT[size_bucket]
        time_lift = _time_lift(observed_at, spec)
        log_sigma = anchors.SECTOR_LOG_SIGMA[sector]

        mu = (
            sector_med
            * region_mult
            * ownership_lift
            * family_lift
            * level_mult
            * education_premium
            * size_lift
            * time_lift
        )

        # nationality lift: non-Saudi at IC3+ tends to have lower base, larger housing
        if not is_saudi:
            mu *= anchors.SAUDI_BASE_LIFT

        # descriptive gender gap: real, present in data so the fairness layer can correct
        if gender == Gender.FEMALE:
            mu *= 1.0 + anchors.GENDER_GAP_FEMALE_DESCRIPTIVE

        # contractor and part-time discounts on base headline
        if employment_type == EmploymentType.CONTRACT:
            mu *= 0.85
        if employment_type == EmploymentType.INTERN:
            mu *= 0.25

        # lognormal noise
        noise = float(rng.normal(loc=0.0, scale=log_sigma))
        base_monthly = float(mu * exp(noise - 0.5 * log_sigma * log_sigma))

        # floor at minimum wage for Saudis; expats can sit lower
        floor = 4000.0 if is_saudi else 1800.0
        base_monthly = max(base_monthly, floor)

        # allowances
        is_exec = level in {Level.M3, Level.M4, Level.M5, Level.D1, Level.D2, Level.D3,
                            Level.VP, Level.SVP, Level.CXO}
        housing_frac = (
            anchors.HOUSING_FRACTION_EXEC if is_exec else anchors.HOUSING_FRACTION_DEFAULT
        )
        housing_monthly = base_monthly * housing_frac
        if not is_saudi and is_exec:
            housing_monthly *= anchors.SAUDI_HOUSING_GAP
        transport_monthly = base_monthly * anchors.TRANSPORT_FRACTION_DEFAULT

        # variable component: sales families get more
        variable_factor = 0.20 if family == JobFamily.SALES else 0.08
        variable_monthly_eq = base_monthly * variable_factor * float(rng.uniform(0.0, 2.0))

        other_fixed_monthly = base_monthly * float(rng.uniform(0.0, 0.05))
        equity_annual_ev = (
            base_monthly * 12.0 * float(rng.uniform(0.05, 0.40))
            if ownership in {Ownership.PIF_BACKED, Ownership.MNC} and is_exec
            else 0.0
        )

        company_id = _stable_company_id(rng, sector, region)

        records.append(
            {
                "observation_id": f"S{i:08d}",
                "source": "synthetic_anchored",
                "observed_at": observed_at.replace(tzinfo=UTC),
                "family": family.value,
                "level": level.value,
                "specialization": None,
                "yoe": round(yoe, 1),
                "education": education.value,
                "is_saudi": is_saudi,
                "gender": gender.value,
                "age_bucket": age_bucket,
                "company_id": company_id,
                "sector": sector.value,
                "ownership": ownership.value,
                "size_bucket": size_bucket,
                "region": region.value,
                "employment_type": employment_type.value,
                "work_mode": work_mode.value,
                "base_monthly": round(base_monthly, 2),
                "housing_monthly": round(housing_monthly, 2),
                "transport_monthly": round(transport_monthly, 2),
                "other_fixed_monthly": round(other_fixed_monthly, 2),
                "variable_monthly_eq": round(variable_monthly_eq, 2),
                "equity_annual_ev": round(equity_annual_ev, 2),
                "confidence": 0.6,
                "quality_flags": (),
            }
        )

    df = pd.DataFrame.from_records(records)
    df["tcc_monthly"] = (
        df["base_monthly"]
        + df["housing_monthly"]
        + df["transport_monthly"]
        + df["other_fixed_monthly"]
        + df["variable_monthly_eq"]
        + df["equity_annual_ev"] / 12.0
    ).round(2)
    return df


def default_spec(*, n_rows: int, seed: int) -> SynthSpec:
    return SynthSpec(
        n_rows=n_rows,
        seed=seed,
        start_date=datetime(2022, 1, 1, tzinfo=UTC),
        end_date=datetime(2026, 5, 1, tzinfo=UTC),
    )
