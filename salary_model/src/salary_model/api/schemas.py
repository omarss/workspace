"""Pydantic request/response schemas for the inference API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, NonNegativeFloat

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


class PredictRequest(BaseModel):
    family: JobFamily
    level: Level
    yoe: float = Field(ge=0.0, le=60.0)
    education: Education = Education.BACHELORS
    skills: list[str] = Field(default_factory=list)
    region: Region
    sector: Sector
    company_ownership: Ownership = Ownership.PRIVATE
    size_bucket: Literal["1-9", "10-49", "50-249", "250-999", "1000+"] = "250-999"
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    work_mode: WorkMode = WorkMode.ONSITE
    is_saudi: bool | None = None
    gender: Gender | None = None
    age_bucket: str | None = None
    as_of: datetime | None = None
    head: Literal["descriptive", "recommendation"] = "descriptive"


class QuantileBlock(BaseModel):
    """Industry-standard percentile bands.

    Convention follows every major compensation survey (Mercer, Korn Ferry, Aon, Hays):
    ``pXX`` is the value below which ``XX%`` of the market falls. So ``p90`` is the
    top decile (only 10% of the market earns more), ``p10`` is the bottom decile
    (only 10% earns less), and ``p50`` is the median. The ``labels`` block surfaces
    a human-readable explanation alongside each number to avoid the common
    misreading.
    """

    p10: NonNegativeFloat
    p25: NonNegativeFloat
    p50: NonNegativeFloat
    p75: NonNegativeFloat
    p90: NonNegativeFloat
    labels: dict[str, str] = Field(
        default_factory=lambda: {
            "p10": "bottom 10% — only 10% of the market earns less",
            "p25": "bottom quartile — 25% earns less",
            "p50": "median — half of the market earns more, half earns less",
            "p75": "top quartile — only 25% earns more",
            "p90": "top 10% — only 10% of the market earns more",
        }
    )


class DescriptiveBlock(BaseModel):
    base: QuantileBlock
    interval_coverage_target: float = 0.80


class RecommendationBlock(BaseModel):
    base_p50_fair: NonNegativeFloat
    delta_vs_descriptive_pct: float
    notes: str


class ConfidenceBlock(BaseModel):
    score: float
    drivers: list[str]


class ComparablesBlock(BaseModel):
    n: int
    parametric_weight: float


class ExplanationFactor(BaseModel):
    feature: str
    shap: float
    human: str


class FairnessBlock(BaseModel):
    flag: Literal["none", "sensitive_used_descriptive", "sensitive_used_recommendation"]
    sensitive_features_used: list[str]


class DataProvenanceBlock(BaseModel):
    """What data went into training this model bundle.

    Surfaces the directive "the model should be built on data, not assumptions" to
    every API consumer. ``trained_on_real_data`` is False whenever the entire training
    set is synthetic; the ``training_mix`` shows the row counts per source.
    """

    trained_on_real_data: bool
    training_mix: dict[str, int]
    snapshot_hash: str


class PredictResponse(BaseModel):
    model_version: str
    currency: Literal["SAR"] = "SAR"
    period: Literal["monthly"] = "monthly"
    as_of: datetime
    head: Literal["descriptive", "recommendation"]
    descriptive: DescriptiveBlock
    recommendation: RecommendationBlock | None = None
    confidence: ConfidenceBlock
    comparables: ComparablesBlock
    explanation: list[ExplanationFactor]
    warnings: list[str] = Field(default_factory=list)
    fairness: FairnessBlock
    data_provenance: DataProvenanceBlock
