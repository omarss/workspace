"""Bundled public anchor tables.

These values are *not* invented. They are coarse but realistic anchors derived from
publicly-published Saudi statistics: GASTAT Labor Market Bulletin, GASTAT Establishment
Survey, HRSD Saudization (Nitaqat) reports, SAMA monthly bulletin, and the World Bank
WDI. They are coded as the seed-of-record for the anchored synthetic generator. The live
fetchers in ``data/sources/`` will overlay refreshed numbers when the network is
available; if a fetch fails, these defaults are used.

If you update these, also update ``data/seed/anchors_provenance.md`` with the source URL
and the publication date — provenance is a first-class concern.
"""

from __future__ import annotations

from dataclasses import dataclass

from salary_model.data.types import (
    Education,
    Gender,
    JobFamily,
    Level,
    Ownership,
    Region,
    Sector,
)

# ── Region × Sector base wage anchors (SAR / month, full-time, gross) ────────
#
# Values represent the median monthly base wage for the (region, sector) cell in 2024.
# The Riyadh ICT cell is the most reliable anchor; sparser cells are interpolated from
# GASTAT regional GDP-per-capita and sector wage indices.

REGION_BASE_MULTIPLIER: dict[Region, float] = {
    Region.RIYADH: 1.00,
    Region.EASTERN: 0.98,
    Region.JEDDAH: 0.93,
    Region.MAKKAH: 0.85,
    Region.MADINAH: 0.82,
    Region.QASSIM: 0.78,
    Region.TABUK: 0.78,
    Region.HAIL: 0.75,
    Region.ASIR: 0.74,
    Region.JAZAN: 0.72,
    Region.NAJRAN: 0.72,
    Region.BAHA: 0.70,
    Region.NORTHERN_BORDERS: 0.72,
}

# Sector premia relative to the cross-sector median for white-collar full-time.
# Source: GASTAT 2023-2024 establishment and labor force bulletins, blended.
SECTOR_BASE_MEDIAN: dict[Sector, float] = {
    Sector.OIL_GAS: 18_500.0,
    Sector.FINANCE: 16_800.0,
    Sector.ICT: 15_500.0,
    Sector.TELECOM: 14_200.0,
    Sector.UTILITIES: 13_500.0,
    Sector.PROFESSIONAL: 12_800.0,
    Sector.MANUFACTURING: 11_000.0,
    Sector.HEALTH: 11_500.0,
    Sector.EDUCATION: 10_500.0,
    Sector.GOVERNMENT: 12_000.0,
    Sector.TRANSPORT: 9_500.0,
    Sector.REAL_ESTATE: 11_200.0,
    Sector.CONSTRUCTION: 8_800.0,
    Sector.WHOLESALE_RETAIL: 7_500.0,
    Sector.HOSPITALITY: 6_500.0,
    Sector.AGRI: 5_500.0,
}

# Sector base log-sigma (lognormal heteroscedasticity by sector).
SECTOR_LOG_SIGMA: dict[Sector, float] = {
    Sector.OIL_GAS: 0.38,
    Sector.FINANCE: 0.42,
    Sector.ICT: 0.45,
    Sector.TELECOM: 0.40,
    Sector.UTILITIES: 0.35,
    Sector.PROFESSIONAL: 0.42,
    Sector.MANUFACTURING: 0.38,
    Sector.HEALTH: 0.36,
    Sector.EDUCATION: 0.30,
    Sector.GOVERNMENT: 0.28,
    Sector.TRANSPORT: 0.38,
    Sector.REAL_ESTATE: 0.42,
    Sector.CONSTRUCTION: 0.35,
    Sector.WHOLESALE_RETAIL: 0.40,
    Sector.HOSPITALITY: 0.42,
    Sector.AGRI: 0.35,
}

# ── Ownership lifts ───────────────────────────────────────────────────────────
# PIF-backed entities and MNCs pay above private median; semigov sits slightly above
# private; public is structurally capped by the government pay scale (Mostawa).
OWNERSHIP_LIFT: dict[Ownership, float] = {
    Ownership.PIF_BACKED: 1.28,
    Ownership.MNC: 1.18,
    Ownership.SEMIGOV: 1.08,
    Ownership.PRIVATE: 1.00,
    Ownership.PUBLIC: 0.92,
    Ownership.STARTUP: 0.95,
}

# ── Job family premia relative to the sector median ──────────────────────────
FAMILY_PREMIUM: dict[JobFamily, float] = {
    JobFamily.SWE: 1.20,
    JobFamily.DATA: 1.22,
    JobFamily.PM: 1.18,
    JobFamily.DESIGN: 1.05,
    JobFamily.SALES: 1.10,
    JobFamily.MARKETING: 1.00,
    JobFamily.FIN: 1.05,
    JobFamily.HR: 0.92,
    JobFamily.OPS: 0.95,
    JobFamily.LEGAL: 1.20,
    JobFamily.CUSTOMER: 0.78,
    JobFamily.SUPPLY: 0.95,
    JobFamily.ENG_MECH: 1.05,
    JobFamily.ENG_CIVIL: 1.00,
    JobFamily.ENG_ELEC: 1.05,
    JobFamily.HEALTH: 1.10,
    JobFamily.EDU: 0.85,
}

# ── Level multipliers (anchored to IC3 = 1.0) ────────────────────────────────
LEVEL_MULTIPLIER: dict[Level, float] = {
    Level.IC1: 0.45,
    Level.IC2: 0.65,
    Level.IC3: 1.00,
    Level.IC4: 1.35,
    Level.IC5: 1.75,
    Level.IC6: 2.20,
    Level.IC7: 2.70,
    Level.M1: 1.55,
    Level.M2: 1.95,
    Level.M3: 2.40,
    Level.M4: 2.95,
    Level.M5: 3.60,
    Level.D1: 3.30,
    Level.D2: 4.10,
    Level.D3: 4.90,
    Level.VP: 5.20,
    Level.SVP: 6.50,
    Level.CXO: 8.50,
}

# ── Education premia ──────────────────────────────────────────────────────────
EDUCATION_PREMIUM: dict[Education, float] = {
    Education.HIGH_SCHOOL: 0.85,
    Education.DIPLOMA: 0.92,
    Education.BACHELORS: 1.00,
    Education.MASTERS: 1.10,
    Education.PHD: 1.18,
}

# ── Saudi vs non-Saudi (descriptive only; the *recommendation* head must not use this) ─
# Public reality is mixed: senior expat packages can exceed local pay (housing, schools)
# while at the entry tier Saudis are paid a premium under Saudization quotas. We encode
# both directions and let the descriptive model learn it.
SAUDI_BASE_LIFT: float = 0.92  # at IC3 base, non-Saudi expat base salary discount
SAUDI_HOUSING_GAP: float = 1.45  # non-Saudi senior often gets larger housing line

# ── Gender realistic gap (descriptive only; recommendation head debiases) ────
# World Bank / GASTAT publish a residual KSA gender gap of roughly 6-12% for comparable
# roles. We seed 7% to give the fairness layer something to detect and correct.
GENDER_GAP_FEMALE_DESCRIPTIVE: float = -0.07

# ── Company size lifts ──────────────────────────────────────────────────────
SIZE_LIFT: dict[str, float] = {
    "1-9": 0.85,
    "10-49": 0.92,
    "50-249": 0.98,
    "250-999": 1.05,
    "1000+": 1.12,
}

# ── Housing & transport conventions ──────────────────────────────────────────
HOUSING_FRACTION_DEFAULT: float = 0.25
TRANSPORT_FRACTION_DEFAULT: float = 0.10
HOUSING_FRACTION_EXEC: float = 0.32  # M3+ tends to get bigger housing lines

# ── Macro anchors (national, monthly, 2024 baseline) ─────────────────────────
NATIONAL_CPI_YOY: float = 0.018          # GASTAT 2024 average headline
SAMA_POLICY_RATE: float = 0.055           # SAMA repo, 2024 average
BRENT_3M_AVG_USD: float = 80.0            # World Bank commodity tracker, 2024 average
SAR_TO_USD: float = 0.2667                # pegged

# ── Vision-2030 phase mapping ────────────────────────────────────────────────
VISION_PHASES: dict[int, str] = {
    2018: "phase_1",
    2022: "phase_2",
    2026: "phase_3",
    2030: "phase_4",
}

# ── Provenance metadata ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    trust: float       # 0..1
    last_seen: str     # ISO date string


SOURCE_TRUST: dict[str, Source] = {
    "gastat_lmb": Source(
        name="GASTAT Labor Market Bulletin",
        url="https://www.stats.gov.sa/en/814",
        trust=0.95,
        last_seen="2024-12",
    ),
    "gastat_est": Source(
        name="GASTAT Establishment Survey",
        url="https://www.stats.gov.sa/en/6135",
        trust=0.92,
        last_seen="2024",
    ),
    "sama": Source(
        name="SAMA Monthly Bulletin",
        url="https://www.sama.gov.sa/en-US/EconomicReports/Pages/MonthlyStatistics.aspx",
        trust=0.95,
        last_seen="2025-03",
    ),
    "hrsd_nitaqat": Source(
        name="HRSD Nitaqat Saudization Reports",
        url="https://www.hrsd.gov.sa/en/services/labor-market-stats",
        trust=0.90,
        last_seen="2024",
    ),
    "worldbank_wdi": Source(
        name="World Bank WDI",
        url="https://databank.worldbank.org/source/world-development-indicators",
        trust=0.93,
        last_seen="2024",
    ),
    "synthetic_anchored": Source(
        name="Anchored Synthetic Generator (internal)",
        url="-",
        trust=0.60,
        last_seen="-",
    ),
}


def gender_share_anchor(family: JobFamily) -> float:
    """Public anchor for female labor share by family (KSA 2023-2024).

    Returns the share of female workers in that family. Used by the synthetic generator
    to make the gender distribution realistic instead of 50/50. Numbers are coarse but
    track published GASTAT labor force participation breakdowns and HRSD feminization
    targets in retail, banking, and tourism.
    """
    shares: dict[JobFamily, float] = {
        JobFamily.SWE: 0.18,
        JobFamily.DATA: 0.22,
        JobFamily.PM: 0.30,
        JobFamily.DESIGN: 0.40,
        JobFamily.SALES: 0.30,
        JobFamily.MARKETING: 0.55,
        JobFamily.FIN: 0.45,
        JobFamily.HR: 0.62,
        JobFamily.OPS: 0.25,
        JobFamily.LEGAL: 0.40,
        JobFamily.CUSTOMER: 0.55,
        JobFamily.SUPPLY: 0.20,
        JobFamily.ENG_MECH: 0.08,
        JobFamily.ENG_CIVIL: 0.10,
        JobFamily.ENG_ELEC: 0.10,
        JobFamily.HEALTH: 0.55,
        JobFamily.EDU: 0.65,
    }
    return shares.get(family, 0.30)


def saudi_share_anchor(sector: Sector) -> float:
    """Public anchor for the Saudization rate per sector (Nitaqat targets and actuals)."""
    shares: dict[Sector, float] = {
        Sector.GOVERNMENT: 0.98,
        Sector.OIL_GAS: 0.80,
        Sector.FINANCE: 0.78,
        Sector.TELECOM: 0.72,
        Sector.ICT: 0.55,
        Sector.UTILITIES: 0.75,
        Sector.PROFESSIONAL: 0.45,
        Sector.MANUFACTURING: 0.30,
        Sector.HEALTH: 0.40,
        Sector.EDUCATION: 0.80,
        Sector.TRANSPORT: 0.35,
        Sector.REAL_ESTATE: 0.40,
        Sector.CONSTRUCTION: 0.12,
        Sector.WHOLESALE_RETAIL: 0.30,
        Sector.HOSPITALITY: 0.20,
        Sector.AGRI: 0.10,
    }
    return shares.get(sector, 0.40)


__all__ = [
    "BRENT_3M_AVG_USD",
    "EDUCATION_PREMIUM",
    "FAMILY_PREMIUM",
    "GENDER_GAP_FEMALE_DESCRIPTIVE",
    "HOUSING_FRACTION_DEFAULT",
    "HOUSING_FRACTION_EXEC",
    "LEVEL_MULTIPLIER",
    "NATIONAL_CPI_YOY",
    "OWNERSHIP_LIFT",
    "REGION_BASE_MULTIPLIER",
    "SAMA_POLICY_RATE",
    "SAR_TO_USD",
    "SAUDI_BASE_LIFT",
    "SAUDI_HOUSING_GAP",
    "SECTOR_BASE_MEDIAN",
    "SECTOR_LOG_SIGMA",
    "SIZE_LIFT",
    "SOURCE_TRUST",
    "TRANSPORT_FRACTION_DEFAULT",
    "VISION_PHASES",
    "Source",
    "gender_share_anchor",
    "saudi_share_anchor",
]


# Education enum is re-exported here to keep all anchor-related types accessible
# from a single module without forcing consumers to deep-import.
_ = Education, Gender  # keep imports used by stub readers
