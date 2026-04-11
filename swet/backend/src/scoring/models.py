"""Scoring and results database models."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base, JSONType


class AssessmentResult(Base):
    """Overall results for a completed assessment."""

    __tablename__ = "assessment_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessments.id", ondelete="CASCADE"), unique=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    overall_proficiency_level: Mapped[int] = mapped_column(SmallInteger, default=0)
    proficiency_label: Mapped[str] = mapped_column(String(50), default="novice")
    total_time_seconds: Mapped[int] = mapped_column(Integer, default=0)
    grading_status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CompetencyScore(Base):
    """Per-competency score breakdown within an assessment result."""

    __tablename__ = "competency_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessment_results.id", ondelete="CASCADE"), index=True
    )
    competency_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("competencies.id", ondelete="CASCADE")
    )
    score: Mapped[float] = mapped_column(Float, default=0.0)
    proficiency_level: Mapped[int] = mapped_column(SmallInteger, default=0)
    questions_total: Mapped[int] = mapped_column(Integer, default=0)
    questions_correct: Mapped[int] = mapped_column(Integer, default=0)
    ai_graded_avg: Mapped[float | None] = mapped_column(Float, nullable=True)


class AnswerGrade(Base):
    """Grade for an individual answer (auto or AI graded)."""

    __tablename__ = "answer_grades"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    answer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("answers.id", ondelete="CASCADE"), unique=True
    )
    grading_method: Mapped[str] = mapped_column(String(10))  # "auto" or "ai"
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    rubric_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    graded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
