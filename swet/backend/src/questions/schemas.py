"""Question-related request/response schemas."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Format validation schemas (SPEC-015)
# These define the contract between generator, renderer, and grader.
# ---------------------------------------------------------------------------

VALID_FORMATS = {"mcq", "code_review", "debugging", "short_answer", "design_prompt"}


class RubricCriterion(BaseModel):
    """Single criterion in a grading rubric."""

    name: str
    description: str
    max_points: int = Field(ge=1)
    key_indicators: list[str] = Field(min_length=1)


class GradingRubric(BaseModel):
    """Grading rubric for non-MCQ formats."""

    criteria: list[RubricCriterion] = Field(min_length=1)
    max_score: int = Field(ge=1)
    passing_threshold: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_score_consistency(self) -> "GradingRubric":
        total_points = sum(c.max_points for c in self.criteria)
        if total_points != self.max_score:
            raise ValueError(
                f"Sum of criteria max_points ({total_points}) "
                f"must equal max_score ({self.max_score})"
            )
        return self


class MCQQuestionData(BaseModel):
    """Validation schema for MCQ question fields."""

    options: dict[str, str]  # Must have exactly keys A, B, C, D
    correct_answer: Literal["A", "B", "C", "D"]

    @field_validator("options")
    @classmethod
    def validate_options(cls, v: dict[str, str]) -> dict[str, str]:
        if set(v.keys()) != {"A", "B", "C", "D"}:
            raise ValueError("MCQ must have exactly options A, B, C, D")
        return v


class CodeBasedQuestionData(BaseModel):
    """Validation schema for code_review and debugging question fields."""

    code_snippet: str = Field(min_length=10)
    language: str = Field(min_length=1)
    grading_rubric: GradingRubric


class QuestionMetadata(BaseModel):
    """Optional metadata attached to generated questions."""

    topics: list[str] = Field(default_factory=list)
    estimated_time_minutes: int = Field(default=1, ge=1)


class GeneratedQuestion(BaseModel):
    """Validates Claude's JSON output for a single generated question.

    Used to parse and validate the structured output from the question generator
    before inserting into the database.
    """

    format: str
    title: str = Field(min_length=5)
    body: str = Field(min_length=10)
    code_snippet: str | None = None
    language: str | None = None
    options: dict[str, str] | None = None
    correct_answer: str | None = None
    grading_rubric: GradingRubric | None = None
    explanation: str = Field(min_length=10)
    metadata: QuestionMetadata | None = None

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        if v not in VALID_FORMATS:
            raise ValueError(f"Invalid format '{v}', must be one of {VALID_FORMATS}")
        return v

    @model_validator(mode="after")
    def validate_format_fields(self) -> "GeneratedQuestion":
        """Ensure format-specific required fields are present."""
        if self.format == "mcq":
            if self.options is None or self.correct_answer is None:
                raise ValueError("MCQ questions require 'options' and 'correct_answer'")
            # Validate MCQ structure
            MCQQuestionData(options=self.options, correct_answer=self.correct_answer)  # type: ignore[arg-type]

        elif self.format in ("code_review", "debugging"):
            if not self.code_snippet or not self.language:
                raise ValueError(f"{self.format} questions require 'code_snippet' and 'language'")
            if self.grading_rubric is None:
                raise ValueError(f"{self.format} questions require 'grading_rubric'")

        elif self.format in ("short_answer", "design_prompt"):
            if self.grading_rubric is None:
                raise ValueError(f"{self.format} questions require 'grading_rubric'")

        return self


# ---------------------------------------------------------------------------
# API request/response schemas
# ---------------------------------------------------------------------------


class QuestionBase(BaseModel):
    """Base question fields visible to clients."""

    id: uuid.UUID
    competency_id: int
    format: str
    difficulty: int
    title: str
    body: str
    code_snippet: str | None
    language: str | None
    options: dict[str, str] | None

    model_config = {"from_attributes": True}


class QuestionResponse(QuestionBase):
    """Question sent to client during assessment (no correct answer)."""

    position: int


class QuestionPoolStatus(BaseModel):
    """Status of a question pool for a given config."""

    config_hash: str
    competency_id: int
    difficulty: int
    format: str
    total_questions: int
    generation_status: str

    model_config = {"from_attributes": True}


class QuestionGenerationRequest(BaseModel):
    """Request to generate questions for a pool."""

    config_hash: str
    competency_id: int
    difficulty: int = Field(ge=1, le=5)
    format: str
    count: int = Field(default=20, ge=1, le=50)


class CompetencyResponse(BaseModel):
    """Competency info for display."""

    id: int
    slug: str
    name: str
    description: str
    category: str

    model_config = {"from_attributes": True}
