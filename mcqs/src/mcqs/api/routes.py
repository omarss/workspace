"""/v1/mcq routes.

Design notes:
* Every data endpoint requires `X-Api-Key` except `/health`.
* `/quiz` strips `is_correct` and `explanation` from the payload so a
  client can show the question without spoiling the answer. The full
  record is reachable via `/questions/{id}` once the user submits.
* Responses are shaped by the Pydantic models in `schemas.py`.
"""

from __future__ import annotations

import random
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from ..config import settings
from ..db import connection
from . import queries
from .deps import AuthDep
from .schemas import (
    HealthResponse,
    Option,
    Pagination,
    Question,
    QuestionsResponse,
    QuizResponse,
    SubjectsResponse,
    SubjectSummary,
    TopicsResponse,
    TopicSummary,
)

_OUTPUT_LETTERS = ("A", "B", "C", "D", "E", "F", "G", "H")

router = APIRouter(prefix="/v1/mcq")

VALID_TYPES = {"knowledge", "analytical", "problem_solving"}


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    with connection() as conn:
        h = queries.health(conn)
    return HealthResponse(status="ok", subjects=h["subjects"], questions=h["questions"])


# ---------------------------------------------------------------------------
# authenticated
# ---------------------------------------------------------------------------


@router.get("/subjects", response_model=SubjectsResponse)
async def subjects(_: AuthDep) -> SubjectsResponse:
    with connection() as conn:
        rows = queries.list_subjects(conn)
    return SubjectsResponse(
        subjects=[
            SubjectSummary(
                slug=r["slug"],
                title=r["title"],
                description=r.get("description"),
                total_questions=r["total_questions"],
                counts_by_type={
                    "knowledge": r["knowledge"],
                    "analytical": r["analytical"],
                    "problem_solving": r["problem_solving"],
                },
                rounds_covered=r["rounds_covered"],
            )
            for r in rows
        ]
    )


@router.get("/topics", response_model=TopicsResponse)
async def topics(
    _: AuthDep,
    subject: Annotated[str, Query(min_length=1, max_length=80)],
) -> TopicsResponse:
    with connection() as conn:
        rows = queries.list_topics(conn, subject=subject)
    return TopicsResponse(
        subject=subject,
        topics=[TopicSummary(slug=r["slug"], title=r["title"], question_count=r["question_count"]) for r in rows],
    )


def _row_to_question(
    r: dict,
    *,
    hide_answer: bool = False,
    option_count: int | None = None,
) -> Question:
    # Shuffle on every retrieval and re-letter A..H — the DB letter is
    # the LLM's emission order, which has positional bias we don't want
    # to leak to consumers. Every request sees a fresh permutation, so
    # two calls for the same question return different orderings.
    #
    # `option_count` (used by /quiz) trims the 8-option store down to a
    # smaller set: always the correct option + (option_count - 1)
    # random distractors, then shuffled together so the correct slot is
    # not positionally predictable.
    stored = list(r["options"])
    if option_count is not None and option_count < len(stored):
        correct = [o for o in stored if o.get("is_correct")]
        distractors = [o for o in stored if not o.get("is_correct")]
        take = max(0, option_count - len(correct))
        sampled = random.sample(distractors, min(take, len(distractors)))
        stored = correct + sampled
    random.shuffle(stored)

    letters = _OUTPUT_LETTERS[: len(stored)]
    opts = [
        Option(
            letter=letters[i],
            text=o["text"],
            is_correct=None if hide_answer else bool(o["is_correct"]),
        )
        for i, o in enumerate(stored)
    ]
    return Question(
        id=r["id"],
        subject=r["subject_slug"],
        type=r["question_type"],
        round=r["round_number"],
        difficulty=r["difficulty"],
        stem=r["stem"],
        options=opts,
        explanation=None if hide_answer else r["explanation"],
        topics=list(r["topics"]),
        created_at=r["created_at"],
    )


@router.get("/questions", response_model=QuestionsResponse)
async def list_questions(
    _: AuthDep,
    subject: Annotated[str | None, Query(max_length=80)] = None,
    type: Annotated[str | None, Query(max_length=32)] = None,  # noqa: A002
    topic: Annotated[str | None, Query(max_length=80)] = None,
    difficulty: Annotated[int | None, Query(ge=1, le=5)] = None,
    round: Annotated[int | None, Query(ge=1)] = None,  # noqa: A002
    limit: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> QuestionsResponse:
    if type is not None and type not in VALID_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"type must be one of: {sorted(VALID_TYPES)}",
        )
    effective_limit = min(limit or settings.api_default_limit, settings.api_max_limit)

    with connection() as conn:
        rows, has_more = queries.list_questions(
            conn,
            subject=subject,
            qtype=type,
            topic=topic,
            difficulty=difficulty,
            round_number=round,
            limit=effective_limit,
            offset=offset,
        )

    return QuestionsResponse(
        questions=[_row_to_question(r) for r in rows],
        pagination=Pagination(limit=effective_limit, offset=offset, has_more=has_more),
    )


@router.get("/questions/{qid}", response_model=Question)
async def get_question(_: AuthDep, qid: int) -> Question:
    with connection() as conn:
        row = queries.get_question(conn, qid)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return _row_to_question(row)


def _parse_csv(raw: str | None) -> list[str] | None:
    """Comma-separated slug list → lowercased list (or None).

    Accepts `None`, `""`, or `"all"` as "no filter". Anything else is
    split on commas, trimmed, lowercased, and deduped while preserving
    order so the SQL `ANY(...)` array stays small and predictable.
    """
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or raw.lower() == "all":
        return None
    seen: set[str] = set()
    out: list[str] = []
    for part in raw.split(","):
        s = part.strip().lower()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out or None


@router.get("/quiz", response_model=QuizResponse)
async def quiz(
    _: AuthDep,
    subject: Annotated[
        str | None,
        Query(
            max_length=800,
            description=(
                "Omit or pass 'all' for a bank-wide random sample. "
                "Comma-separated slugs filter to those subjects."
            ),
        ),
    ] = None,
    topic: Annotated[
        str | None,
        Query(
            max_length=800,
            description=(
                "Optional comma-separated topic slugs. A question matches "
                "if it is tagged with ANY of them."
            ),
        ),
    ] = None,
    type: Annotated[str | None, Query(max_length=32)] = None,  # noqa: A002
    count: Annotated[int, Query(ge=1, le=50)] = 10,
    options: Annotated[
        int,
        Query(
            ge=2,
            le=8,
            description=(
                "How many options per question to return (quiz mode). "
                "Correct answer is always included, the rest are random "
                "distractors. Default 4."
            ),
        ),
    ] = 4,
) -> QuizResponse:
    if type is not None and type not in VALID_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"type must be one of: {sorted(VALID_TYPES)}",
        )
    subjects = _parse_csv(subject)
    topics = _parse_csv(topic)

    with connection() as conn:
        rows = queries.random_quiz(
            conn, subjects=subjects, topics=topics, qtype=type, count=count
        )

    # Echo back whichever filter the client sent, normalised. `None`
    # means "bank-wide / any topic"; a joined list reflects the actual
    # subjects/topics that were in scope.
    subject_echo = ",".join(subjects) if subjects else None
    return QuizResponse(
        subject=subject_echo,
        type=type,  # type: ignore[arg-type]
        questions=[
            _row_to_question(r, hide_answer=True, option_count=options)
            for r in rows
        ],
    )
