"""Pydantic models for questions, grades, and LLM responses."""

from pydantic import BaseModel, Field


class GeneratedQuestion(BaseModel):
    """A question as returned by the LLM."""

    title: str
    body: str
    code_snippet: str | None = None
    language: str | None = None
    options: dict[str, str] | None = None  # {"A": "...", "B": "...", ...}
    correct_answer: str | None = None
    grading_rubric: dict | None = None
    explanation: str | None = None
    explanation_detail: dict | None = None  # {why_correct, why_others_fail, principle}
    metadata: dict | None = None


class CriterionScore(BaseModel):
    """Score for a single rubric criterion."""

    name: str
    score: int = Field(ge=0)
    max_points: int
    feedback: str


class GradeResult(BaseModel):
    """Structured result from AI grading."""

    criteria_scores: list[CriterionScore]
    total_score: int = Field(ge=0)
    max_score: int
    normalized_score: float = Field(ge=0.0, le=1.0)
    overall_feedback: str
