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
    # Per omono/FEEDBACK.md §11.2 — number of source docs under this
    # subject that the /v1/mcq/docs endpoints will serve. 0 when no
    # docs have been ingested (or none have been backfilled with
    # `content_text` yet).
    doc_count: int = 0


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


# ---------------------------------------------------------------------------
# Docs browsing — spec in omono/FEEDBACK.md §11
# ---------------------------------------------------------------------------


class DocSummary(BaseModel):
    # `id` is the numeric source_docs primary key rendered as a string
    # so JS / Kotlin clients don't have to worry about 53-bit int
    # ceilings. (The omono client reads this field as a string
    # already.)
    id: str
    title: str
    path: str
    size_bytes: int
    updated_at: datetime


class DocListResponse(BaseModel):
    subject: str
    docs: list[DocSummary]


class Doc(BaseModel):
    id: str
    subject: str
    title: str
    path: str
    markdown: str
    size_bytes: int
    updated_at: datetime
