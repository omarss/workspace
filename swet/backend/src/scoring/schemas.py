"""Scoring and results schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class CompetencyScoreResponse(BaseModel):
    """Per-competency score in results."""

    competency_id: int
    competency_name: str | None = None
    score: float
    proficiency_level: int
    questions_total: int
    questions_correct: int
    ai_graded_avg: float | None


class ResultResponse(BaseModel):
    """Full assessment results."""

    id: uuid.UUID
    assessment_id: uuid.UUID
    overall_score: float
    overall_proficiency_level: int
    proficiency_label: str
    total_time_seconds: int
    grading_status: str
    competency_scores: list[CompetencyScoreResponse]
    created_at: datetime

    model_config = {"from_attributes": True}


class RadarDataPoint(BaseModel):
    """Single data point for the radar chart."""

    competency: str
    score: float
    max_score: float = 100.0


class RadarResponse(BaseModel):
    """Radar chart data for results visualization."""

    data: list[RadarDataPoint]


class GradingStatusResponse(BaseModel):
    """Current AI grading progress."""

    assessment_id: uuid.UUID
    grading_status: str
    total_to_grade: int
    graded_count: int
    progress_percent: float


class ResultSummary(BaseModel):
    """Lightweight result entry for history lists."""

    id: uuid.UUID
    assessment_id: uuid.UUID
    overall_score: float
    proficiency_label: str
    total_time_seconds: int
    grading_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class HistoryResponse(BaseModel):
    """Paginated assessment history."""

    items: list[ResultSummary]
    total_count: int
    page: int
    per_page: int


class HistoryStatsResponse(BaseModel):
    """Summary statistics across all user assessments."""

    total_assessments: int
    average_score: float
    highest_score: float
    latest_proficiency_label: str


class TrendDataPoint(BaseModel):
    """Single data point for the score trend chart."""

    date: datetime
    score: float


class TrendResponse(BaseModel):
    """Score trend over time."""

    data: list[TrendDataPoint]


class CompareResponse(BaseModel):
    """Side-by-side comparison of two assessment results."""

    results: list[ResultResponse]
