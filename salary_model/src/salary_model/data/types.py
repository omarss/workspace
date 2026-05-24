"""Typed primitives for the data layer.

These models define the canonical shape of compensation data inside the system. Sources
that produce different shapes must be normalized to these types before they go
downstream.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat


class Region(StrEnum):
    """Saudi administrative regions plus three explicit metro tags."""

    RIYADH = "RUH"
    JEDDAH = "JED"
    MAKKAH = "MAK"
    MADINAH = "MAD"
    EASTERN = "EST"
    QASSIM = "QAS"
    HAIL = "HAI"
    TABUK = "TAB"
    ASIR = "ASR"
    JAZAN = "JAZ"
    NAJRAN = "NJR"
    BAHA = "BAH"
    NORTHERN_BORDERS = "NOR"


class Ownership(StrEnum):
    """Employer ownership archetypes meaningful to KSA compensation."""

    PUBLIC = "public"
    SEMIGOV = "semigov"
    PRIVATE = "private"
    PIF_BACKED = "pif_backed"
    MNC = "mnc"
    STARTUP = "startup"


class JobFamily(StrEnum):
    """Coarse job-family taxonomy. Specialization is a separate free-text field."""

    SWE = "SWE"
    DATA = "DATA"
    PM = "PM"
    DESIGN = "DESIGN"
    SALES = "SALES"
    MARKETING = "MARKETING"
    FIN = "FIN"
    HR = "HR"
    OPS = "OPS"
    LEGAL = "LEGAL"
    CUSTOMER = "CUSTOMER"
    SUPPLY = "SUPPLY"
    ENG_MECH = "ENG_MECH"
    ENG_CIVIL = "ENG_CIVIL"
    ENG_ELEC = "ENG_ELEC"
    HEALTH = "HEALTH"
    EDU = "EDU"


class Level(StrEnum):
    """Seniority levels with a monotone global rank (1..20)."""

    IC1 = "IC1"
    IC2 = "IC2"
    IC3 = "IC3"
    IC4 = "IC4"
    IC5 = "IC5"
    IC6 = "IC6"
    IC7 = "IC7"
    M1 = "M1"
    M2 = "M2"
    M3 = "M3"
    M4 = "M4"
    M5 = "M5"
    D1 = "D1"
    D2 = "D2"
    D3 = "D3"
    VP = "VP"
    SVP = "SVP"
    CXO = "CXO"


LEVEL_RANK: dict[Level, int] = {
    Level.IC1: 1, Level.IC2: 2, Level.IC3: 3, Level.IC4: 4, Level.IC5: 5,
    Level.IC6: 6, Level.IC7: 7,
    Level.M1: 5, Level.M2: 7, Level.M3: 9, Level.M4: 11, Level.M5: 13,
    Level.D1: 12, Level.D2: 14, Level.D3: 16,
    Level.VP: 17, Level.SVP: 18, Level.CXO: 20,
}


class Sector(StrEnum):
    """ISIC4-aligned sector codes; coarse enough to be tractable."""

    AGRI = "A"
    OIL_GAS = "B"
    MANUFACTURING = "C"
    UTILITIES = "D"
    CONSTRUCTION = "F"
    WHOLESALE_RETAIL = "G"
    TRANSPORT = "H"
    HOSPITALITY = "I"
    ICT = "J62"
    TELECOM = "J61"
    FINANCE = "K"
    REAL_ESTATE = "L"
    PROFESSIONAL = "M"
    EDUCATION = "P"
    HEALTH = "Q"
    GOVERNMENT = "O"


class EmploymentType(StrEnum):
    FULL_TIME = "ft"
    PART_TIME = "pt"
    CONTRACT = "contract"
    INTERN = "intern"


class WorkMode(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"


class Gender(StrEnum):
    MALE = "M"
    FEMALE = "F"


class Education(StrEnum):
    HIGH_SCHOOL = "hs"
    DIPLOMA = "diploma"
    BACHELORS = "bachelors"
    MASTERS = "masters"
    PHD = "phd"


EDUCATION_RANK: dict[Education, int] = {
    Education.HIGH_SCHOOL: 0,
    Education.DIPLOMA: 1,
    Education.BACHELORS: 2,
    Education.MASTERS: 3,
    Education.PHD: 4,
}


class CompensationComponents(BaseModel):
    """Canonical compensation tuple in SAR per month, gross.

    See §4 of the design document. `variable_monthly_eq` is the annualized expected
    variable pay divided by twelve.
    """

    model_config = ConfigDict(frozen=True)

    base_monthly: NonNegativeFloat
    housing_monthly: NonNegativeFloat = 0.0
    transport_monthly: NonNegativeFloat = 0.0
    other_fixed_monthly: NonNegativeFloat = 0.0
    variable_monthly_eq: NonNegativeFloat = 0.0
    equity_annual_ev: NonNegativeFloat = 0.0

    @property
    def tcc_monthly(self) -> float:
        return float(
            self.base_monthly
            + self.housing_monthly
            + self.transport_monthly
            + self.other_fixed_monthly
            + self.variable_monthly_eq
            + (self.equity_annual_ev / 12.0)
        )


YearsExperience = Annotated[float, Field(ge=0.0, le=60.0)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class SalaryObservation(BaseModel):
    """One canonical salary observation post-normalization. Strict-typed end-to-end."""

    model_config = ConfigDict(frozen=True)

    observation_id: str
    source: str
    observed_at: datetime
    # subject
    family: JobFamily
    level: Level
    specialization: str | None = None
    yoe: YearsExperience
    education: Education
    # sensitive (gated downstream)
    is_saudi: bool
    gender: Gender
    age_bucket: str  # e.g. "25-29"
    # employer
    company_id: str | None
    sector: Sector
    ownership: Ownership
    size_bucket: str  # 1-9 / 10-49 / 50-249 / 250-999 / 1000+
    region: Region
    employment_type: EmploymentType
    work_mode: WorkMode
    # comp
    comp: CompensationComponents
    # quality
    confidence: Confidence
    quality_flags: tuple[str, ...] = ()
    # skills (free-form for now; normalized in feature pipeline)
    skills: tuple[str, ...] = ()
