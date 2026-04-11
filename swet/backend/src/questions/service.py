"""Question service layer (SPEC-013).

Provides question retrieval and pool readiness checking
for the assessment engine.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.questions.models import Question, QuestionPool, UserQuestionHistory


async def get_questions_for_pool(
    db: AsyncSession,
    pool_id: uuid.UUID,
) -> list[Question]:
    """Get all questions belonging to a specific pool."""
    result = await db.execute(select(Question).where(Question.pool_id == pool_id))
    return list(result.scalars().all())


async def get_questions_by_criteria(
    db: AsyncSession,
    config_hash: str,
    competency_id: int,
    difficulty: int,
    question_format: str,
    exclude_question_ids: set[uuid.UUID] | None = None,
) -> list[Question]:
    """Get available questions matching criteria, optionally excluding seen ones.

    Used by the assessment engine to select questions for an assessment.
    Only returns questions from completed pools.
    """
    # Find completed pool
    pool_result = await db.execute(
        select(QuestionPool).where(
            QuestionPool.config_hash == config_hash,
            QuestionPool.competency_id == competency_id,
            QuestionPool.difficulty == difficulty,
            QuestionPool.format == question_format,
            QuestionPool.generation_status == "complete",
        )
    )
    pool = pool_result.scalar_one_or_none()
    if pool is None:
        return []

    # Get questions from the pool
    query = select(Question).where(Question.pool_id == pool.id)

    if exclude_question_ids:
        query = query.where(Question.id.notin_(exclude_question_ids))

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_seen_question_ids(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> set[uuid.UUID]:
    """Get all question IDs that a user has previously seen."""
    result = await db.execute(
        select(UserQuestionHistory.question_id).where(UserQuestionHistory.user_id == user_id)
    )
    return {row[0] for row in result.all()}


async def record_seen_questions(
    db: AsyncSession,
    user_id: uuid.UUID,
    question_ids: list[uuid.UUID],
) -> None:
    """Record that a user has seen specific questions (for uniqueness enforcement)."""
    for qid in question_ids:
        db.add(UserQuestionHistory(user_id=user_id, question_id=qid))
    await db.flush()
