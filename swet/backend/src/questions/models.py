"""Question-related database models."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base, JSONType


class Competency(Base):
    """The 12 engineering competency groups."""

    __tablename__ = "competencies"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50))


class RoleCompetencyWeight(Base):
    """How much each competency matters for a given role."""

    __tablename__ = "role_competency_weights"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(String(100), index=True)
    competency_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("competencies.id", ondelete="CASCADE")
    )
    weight: Mapped[float] = mapped_column()
    question_count: Mapped[int] = mapped_column(SmallInteger)

    __table_args__ = (UniqueConstraint("role", "competency_id"),)


class QuestionPool(Base):
    """Cached pool of questions for a specific config + competency + difficulty."""

    __tablename__ = "question_pools"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    competency_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("competencies.id", ondelete="CASCADE")
    )
    difficulty: Mapped[int] = mapped_column(SmallInteger)
    format: Mapped[str] = mapped_column(String(30))
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    generation_status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Question(Base):
    """Individual assessment question."""

    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question_pools.id", ondelete="CASCADE")
    )
    competency_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("competencies.id", ondelete="CASCADE")
    )
    format: Mapped[str] = mapped_column(String(30))
    difficulty: Mapped[int] = mapped_column(SmallInteger)
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    code_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    options: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    correct_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    grading_rubric: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONType, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserQuestionHistory(Base):
    """Track which questions each user has seen (for uniqueness enforcement)."""

    __tablename__ = "user_question_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE")
    )
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "question_id"),)
