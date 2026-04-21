"""Pydantic response models for /v1/mcq."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

QuestionType = Literal["knowledge", "analytical", "problem_solving"]


class Pagination(BaseModel):
    limit: int
    offset: int
    has_more: bool


class SubjectSummary(BaseModel):
    slug: str
    title: str
    description: str | None = None
    total_questions: int
    counts_by_type: dict[str, int]
    rounds_covered: int


class SubjectsResponse(BaseModel):
    subjects: list[SubjectSummary]


class TopicSummary(BaseModel):
    slug: str
    title: str
    question_count: int


class TopicsResponse(BaseModel):
    subject: str
    topics: list[TopicSummary]


class Option(BaseModel):
    letter: str
    text: str
    is_correct: bool | None = Field(
        default=None,
        description="Hidden in `/quiz` responses, present everywhere else.",
    )


class Question(BaseModel):
    id: int
    subject: str
    type: QuestionType
    round: int
    difficulty: int
    stem: str
    options: list[Option]
    explanation: str | None = Field(
        default=None,
        description="Hidden in `/quiz` responses, present everywhere else.",
    )
    topics: list[str]
    created_at: datetime


class QuestionsResponse(BaseModel):
    questions: list[Question]
    pagination: Pagination


class QuizResponse(BaseModel):
    subject: str | None = Field(
        default=None,
        description=(
            "Echo of the subjects filter. Null means the sample was "
            "bank-wide; a single slug or comma-joined list otherwise."
        ),
    )
    type: QuestionType | None = None
    questions: list[Question]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    subjects: int
    questions: int
