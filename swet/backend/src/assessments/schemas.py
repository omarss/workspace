"""Assessment request/response schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AssessmentCreateRequest(BaseModel):
    """Request to start a new assessment."""

    is_timed: bool = False
    time_limit_minutes: int | None = Field(default=None, ge=30, le=300)


class AnswerSubmitRequest(BaseModel):
    """Request to submit or auto-save an answer."""

    question_id: uuid.UUID
    response_text: str | None = None
    selected_option: str | None = None
    time_spent_seconds: int = Field(default=0, ge=0)
    is_auto_saved: bool = False


class AssessmentResponse(BaseModel):
    """Assessment summary response."""

    id: uuid.UUID
    status: str
    total_questions: int
    current_question_index: int
    is_timed: bool
    time_limit_minutes: int | None
    started_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class AssessmentListResponse(BaseModel):
    """List of user's assessments."""

    assessments: list[AssessmentResponse]
    total: int


class QuestionResponse(BaseModel):
    """Question data sent to the client (no correct answer)."""

    id: uuid.UUID
    competency_id: int
    format: str
    difficulty: int
    title: str
    body: str
    code_snippet: str | None
    language: str | None
    options: dict[str, Any] | None
    position: int

    model_config = {"from_attributes": True}


class ProgressResponse(BaseModel):
    """Assessment progress summary."""

    assessment_id: uuid.UUID
    total_questions: int
    answered_count: int
    current_index: int
    time_elapsed_seconds: int | None
    time_remaining_seconds: int | None
