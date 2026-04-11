"""Assessment API endpoints."""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.assessments.models import AssessmentQuestion
from src.assessments.schemas import (
    AnswerSubmitRequest,
    AssessmentCreateRequest,
    AssessmentListResponse,
    AssessmentResponse,
    ProgressResponse,
    QuestionResponse,
)
from src.assessments.service import (
    complete_assessment,
    create_assessment,
    get_assessment,
    get_progress,
    list_assessments,
    submit_answer,
)
from src.auth.models import User
from src.database import async_session_factory, get_db
from src.dependencies import get_current_user
from src.errors import AppError, NotFoundError
from src.onboarding.service import get_profile
from src.questions.cache import (
    create_pending_pools,
    generate_next_pending_pool,
    get_required_pools_status,
)
from src.questions.models import Question

logger = logging.getLogger(__name__)

router = APIRouter()

# Track active generation tasks to prevent duplicates
_generation_tasks: dict[str, asyncio.Task[None]] = {}


GENERATION_CONCURRENCY = 3  # Number of pools to generate in parallel
MAX_CONSECUTIVE_FAILURES = 10  # Stop after this many consecutive failures


async def _generate_one_pool(
    config_hash: str,
    role: str,
    languages: list[str],
    frameworks: list[str],
) -> bool:
    """Generate a single pending pool with its own DB session.

    Returns True if a pool was generated, False if none left.
    Exceptions are caught and logged so the caller can continue.
    """
    try:
        async with async_session_factory() as db:
            generated = await generate_next_pending_pool(
                db, config_hash, role, languages, frameworks
            )
            await db.commit()
        return generated
    except Exception:
        logger.exception("Pool generation failed for config_hash=%s", config_hash[:16])
        return False


async def _run_generation(
    config_hash: str,
    role: str,
    languages: list[str],
    frameworks: list[str],
) -> None:
    """Generate pools sequentially, one at a time.

    Sequential generation avoids circuit breaker issues (5 concurrent
    failures would trip it immediately) and prevents idle-in-transaction
    locks from piling up. Each pool takes ~60-90s, so progress is still
    visible via the status endpoint.
    """
    consecutive_failures = 0
    total_generated = 0

    try:
        while consecutive_failures < MAX_CONSECUTIVE_FAILURES:
            generated = await _generate_one_pool(
                config_hash, role, languages, frameworks
            )

            if generated:
                total_generated += 1
                consecutive_failures = 0
                logger.info(
                    "Pool generation progress: %d completed (config=%s)",
                    total_generated,
                    config_hash[:16],
                )
            else:
                # No pending pools left — check if we're actually done
                # or if generate_next_pending_pool returned False due to
                # all pools being complete/failed
                async with async_session_factory() as db:
                    status = await get_required_pools_status(db, config_hash, role)

                pending = status.get("pending", 0) + status.get("generating", 0)
                if pending == 0:
                    break  # All done

                # Still pending pools but generation returned False —
                # likely a transient issue, count as failure
                consecutive_failures += 1
                logger.warning(
                    "Generation returned False but %d pools still pending, "
                    "consecutive_failures=%d (config=%s)",
                    pending,
                    consecutive_failures,
                    config_hash[:16],
                )
                # Brief backoff before retrying
                await asyncio.sleep(2)

        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            logger.error(
                "Stopping generation after %d consecutive failures (config=%s)",
                MAX_CONSECUTIVE_FAILURES,
                config_hash[:16],
            )

        logger.info(
            "Background generation finished: %d pools generated (config=%s)",
            total_generated,
            config_hash[:16],
        )
    except Exception:
        logger.exception("Background generation crashed for config_hash=%s", config_hash[:16])
    finally:
        _generation_tasks.pop(config_hash, None)


@router.get("/pools/status")
async def pools_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Check the generation status of question pools for the current user's config."""
    profile = await get_profile(db, current_user.id)
    if not profile or not profile.config_hash:
        raise AppError("Complete onboarding first", status_code=400)

    config_hash = profile.config_hash
    status = await get_required_pools_status(db, config_hash, profile.primary_role)
    total = sum(status.values())
    ready = total > 0 and status.get("pending", 0) == 0 and status.get("generating", 0) == 0
    generating = config_hash in _generation_tasks and not _generation_tasks[config_hash].done()
    return {"ready": ready, "generating": generating, "pools": status, "total": total}


@router.post("/pools/generate")
async def generate_pools(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Trigger question pool generation in the background.

    Creates all required pool records (pending) immediately so progress
    tracking is accurate, then generates them one by one in a background task.
    Each pool commits independently so progress is visible in real time.

    Returns immediately. Poll GET /pools/status to track progress.
    """
    profile = await get_profile(db, current_user.id)
    if not profile or not profile.config_hash:
        raise AppError("Complete onboarding first", status_code=400)

    config_hash = profile.config_hash

    # Create all required pool records so the total count is accurate
    await create_pending_pools(db, config_hash, profile.primary_role)

    # Don't start duplicate generation
    if config_hash not in _generation_tasks or _generation_tasks[config_hash].done():
        technologies = profile.technologies or {}
        languages = technologies.get("languages", [])
        frameworks = technologies.get("frameworks", [])

        task = asyncio.create_task(
            _run_generation(config_hash, profile.primary_role, languages, frameworks)
        )
        _generation_tasks[config_hash] = task

    status = await get_required_pools_status(db, config_hash, profile.primary_role)
    total = sum(status.values())
    return {"generating": True, "pools": status, "total": total}


@router.post("", response_model=AssessmentResponse, status_code=201)
async def start_assessment(
    data: AssessmentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AssessmentResponse:
    """Start a new assessment."""
    profile = await get_profile(db, current_user.id)
    if not profile or not profile.config_hash:
        raise AppError("Complete onboarding before starting an assessment", status_code=400)

    assessment = await create_assessment(
        db, current_user.id, profile.config_hash, profile.primary_role, data
    )
    return AssessmentResponse.model_validate(assessment)


@router.get("", response_model=AssessmentListResponse)
async def get_assessments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """List all assessments for the current user."""
    assessments = await list_assessments(db, current_user.id)
    return {
        "assessments": [AssessmentResponse.model_validate(a) for a in assessments],
        "total": len(assessments),
    }


@router.get("/{assessment_id}", response_model=AssessmentResponse)
async def get_assessment_detail(
    assessment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AssessmentResponse:
    """Get assessment details."""
    assessment = await get_assessment(db, assessment_id, current_user.id)
    return AssessmentResponse.model_validate(assessment)


@router.post("/{assessment_id}/answers", status_code=200)
async def save_answer(
    assessment_id: uuid.UUID,
    data: AnswerSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Submit or auto-save an answer."""
    answer = await submit_answer(db, assessment_id, current_user.id, data)
    return {"id": str(answer.id), "saved": True}


@router.post("/{assessment_id}/complete", response_model=AssessmentResponse)
async def complete(
    assessment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AssessmentResponse:
    """Complete an assessment and trigger grading."""
    assessment = await complete_assessment(db, assessment_id, current_user.id)
    return AssessmentResponse.model_validate(assessment)


@router.get("/{assessment_id}/progress", response_model=ProgressResponse)
async def progress(
    assessment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Get progress summary for an assessment."""
    return await get_progress(db, assessment_id, current_user.id)


@router.get("/{assessment_id}/questions", response_model=list[QuestionResponse])
async def get_questions(
    assessment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> list[QuestionResponse]:
    """Get assessment questions (paginated, no correct answers)."""
    # Verify assessment belongs to user
    await get_assessment(db, assessment_id, current_user.id)

    # Join assessment_questions with questions, ordered by position
    result = await db.execute(
        select(Question, AssessmentQuestion.position)
        .join(AssessmentQuestion, AssessmentQuestion.question_id == Question.id)
        .where(AssessmentQuestion.assessment_id == assessment_id)
        .order_by(AssessmentQuestion.position)
        .offset(offset)
        .limit(limit)
    )

    return [
        QuestionResponse(
            id=q.id,
            competency_id=q.competency_id,
            format=q.format,
            difficulty=q.difficulty,
            title=q.title,
            body=q.body,
            code_snippet=q.code_snippet,
            language=q.language,
            options=q.options,
            position=pos,
        )
        for q, pos in result.all()
    ]


@router.get("/{assessment_id}/questions/{position}", response_model=QuestionResponse)
async def get_question_by_position(
    assessment_id: uuid.UUID,
    position: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuestionResponse:
    """Get a single question by its position in the assessment."""
    # Verify assessment belongs to user
    await get_assessment(db, assessment_id, current_user.id)

    result = await db.execute(
        select(Question, AssessmentQuestion.position)
        .join(AssessmentQuestion, AssessmentQuestion.question_id == Question.id)
        .where(
            AssessmentQuestion.assessment_id == assessment_id,
            AssessmentQuestion.position == position,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Question at position", position)

    q, pos = row
    return QuestionResponse(
        id=q.id,
        competency_id=q.competency_id,
        format=q.format,
        difficulty=q.difficulty,
        title=q.title,
        body=q.body,
        code_snippet=q.code_snippet,
        language=q.language,
        options=q.options,
        position=pos,
    )
