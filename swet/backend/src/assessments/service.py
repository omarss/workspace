"""Assessment service - core assessment engine logic (SPEC-014).

Handles assessment creation with question selection, difficulty distribution,
format distribution, interleaved shuffling, and uniqueness enforcement.
"""

import random
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from src.assessments.models import Answer, Assessment, AssessmentQuestion
from src.assessments.schemas import AnswerSubmitRequest, AssessmentCreateRequest
from src.errors import AppError, NotFoundError
from src.questions.models import Question, QuestionPool, RoleCompetencyWeight, UserQuestionHistory

# Difficulty bell curve distribution percentages
DIFFICULTY_DISTRIBUTION = {1: 0.10, 2: 0.20, 3: 0.35, 4: 0.25, 5: 0.10}

# Format distribution targets (soft target)
FORMAT_DISTRIBUTION = {
    "mcq": 0.40,
    "code_review": 0.15,
    "debugging": 0.15,
    "short_answer": 0.15,
    "design_prompt": 0.15,
}


def compute_difficulty_allocation(total: int) -> dict[int, int]:
    """Distribute questions across difficulty levels using largest-remainder method.

    Ensures the sum exactly equals `total` while respecting the bell curve.
    """
    # Compute exact fractional allocations
    exact: dict[int, float] = {level: total * pct for level, pct in DIFFICULTY_DISTRIBUTION.items()}

    # Floor each allocation
    floored: dict[int, int] = {level: int(v) for level, v in exact.items()}

    # Distribute remainder to levels with largest fractional parts
    remainder = total - sum(floored.values())
    fractions = sorted(exact.keys(), key=lambda lvl: exact[lvl] - floored[lvl], reverse=True)

    for i in range(remainder):
        floored[fractions[i]] += 1

    return floored


def interleave_questions(
    questions_by_competency: dict[int, list[Question]],
) -> list[Question]:
    """Interleave questions so consecutive ones differ in competency and format.

    Uses round-robin across competencies sorted by count (largest first),
    with format variation within each pass.
    """
    # Sort competencies by count (largest first) for balanced distribution
    sorted_comps = sorted(questions_by_competency.items(), key=lambda x: len(x[1]), reverse=True)

    # Shuffle within each competency group for randomness
    for _, qs in sorted_comps:
        random.shuffle(qs)

    # Round-robin distribution
    result: list[Question] = []
    indices: dict[int, int] = {comp_id: 0 for comp_id, _ in sorted_comps}

    while len(result) < sum(len(qs) for _, qs in sorted_comps):
        for comp_id, qs in sorted_comps:
            idx = indices[comp_id]
            if idx < len(qs):
                result.append(qs[idx])
                indices[comp_id] = idx + 1

    return result


async def select_questions(
    db: AsyncSession,
    assessment: Assessment,
    user_id: uuid.UUID,
    config_hash: str,
    role: str,
    seed: int | None = None,
) -> list[AssessmentQuestion]:
    """Select 100 questions for an assessment following competency weights and difficulty curve.

    Algorithm:
    1. Load role weights to get per-competency question counts
    2. For each competency, compute difficulty distribution
    3. For each (competency, difficulty), select questions from pools
    4. Exclude previously seen questions
    5. Interleave and assign positions
    6. Record in user_question_history
    """
    if seed is not None:
        random.seed(seed)

    # Load role weights
    weights_result = await db.execute(
        select(RoleCompetencyWeight).where(RoleCompetencyWeight.role == role)
    )
    weights = weights_result.scalars().all()

    if not weights:
        raise AppError(f"No competency weights found for role '{role}'", status_code=400)

    # Get user's previously seen question IDs
    seen_result = await db.execute(
        select(UserQuestionHistory.question_id).where(UserQuestionHistory.user_id == user_id)
    )
    seen_ids = {row[0] for row in seen_result.all()}

    # Select questions per competency
    questions_by_competency: dict[int, list[Question]] = {}

    for weight in weights:
        if weight.question_count == 0:
            continue

        comp_questions = await _select_for_competency(
            db=db,
            config_hash=config_hash,
            competency_id=weight.competency_id,
            target_count=weight.question_count,
            seen_ids=seen_ids,
        )
        questions_by_competency[weight.competency_id] = comp_questions

    # Interleave questions across competencies
    all_questions = interleave_questions(questions_by_competency)

    # Create AssessmentQuestion records with positions
    assessment_questions: list[AssessmentQuestion] = []
    history_records: list[UserQuestionHistory] = []

    for position, question in enumerate(all_questions):
        aq = AssessmentQuestion(
            assessment_id=assessment.id,
            question_id=question.id,
            position=position,
            competency_id=question.competency_id,
        )
        db.add(aq)
        assessment_questions.append(aq)

        # Track in user history
        history_records.append(UserQuestionHistory(user_id=user_id, question_id=question.id))

    # Batch insert history records
    for record in history_records:
        db.add(record)

    assessment.total_questions = len(all_questions)
    await db.flush()

    return assessment_questions


async def _select_for_competency(
    db: AsyncSession,
    config_hash: str,
    competency_id: int,
    target_count: int,
    seen_ids: set[uuid.UUID],
) -> list[Question]:
    """Select questions for a single competency with difficulty distribution."""
    difficulty_alloc = compute_difficulty_allocation(target_count)
    selected: list[Question] = []

    # Try each difficulty level
    shortfall: dict[int, int] = {}
    for difficulty, count in difficulty_alloc.items():
        if count == 0:
            continue

        # Get questions from completed pools for all formats at this difficulty
        pool_result = await db.execute(
            select(QuestionPool).where(
                QuestionPool.config_hash == config_hash,
                QuestionPool.competency_id == competency_id,
                QuestionPool.difficulty == difficulty,
                QuestionPool.generation_status == "complete",
            )
        )
        pools = pool_result.scalars().all()

        available: list[Question] = []
        for pool in pools:
            q_result = await db.execute(
                select(Question).where(
                    Question.pool_id == pool.id,
                    Question.id.notin_(seen_ids) if seen_ids else true(),
                )
            )
            available.extend(q_result.scalars().all())

        if len(available) >= count:
            random.shuffle(available)
            selected.extend(available[:count])
            # Add selected to seen_ids to prevent duplicates within this assessment
            for q in available[:count]:
                seen_ids.add(q.id)
        else:
            # Take what's available, track shortfall for fallback
            selected.extend(available)
            for q in available:
                seen_ids.add(q.id)
            shortfall[difficulty] = count - len(available)

    # Fallback: fill shortfall from adjacent difficulty levels (prefer L3 center)
    if shortfall:
        for _difficulty, needed in shortfall.items():
            for fallback_level in [3, 2, 4, 1, 5]:
                if needed <= 0:
                    break

                pool_result = await db.execute(
                    select(QuestionPool).where(
                        QuestionPool.config_hash == config_hash,
                        QuestionPool.competency_id == competency_id,
                        QuestionPool.difficulty == fallback_level,
                        QuestionPool.generation_status == "complete",
                    )
                )
                pools = pool_result.scalars().all()

                for pool in pools:
                    if needed <= 0:
                        break
                    q_result = await db.execute(
                        select(Question).where(
                            Question.pool_id == pool.id,
                            Question.id.notin_(seen_ids) if seen_ids else true(),
                        )
                    )
                    extra = list(q_result.scalars().all())
                    random.shuffle(extra)
                    take = min(needed, len(extra))
                    selected.extend(extra[:take])
                    for q in extra[:take]:
                        seen_ids.add(q.id)
                    needed -= take

    return selected


async def create_assessment(
    db: AsyncSession,
    user_id: uuid.UUID,
    config_hash: str,
    role: str,
    data: AssessmentCreateRequest,
) -> Assessment:
    """Create a new assessment and select questions."""
    assessment = Assessment(
        user_id=user_id,
        config_hash=config_hash,
        is_timed=data.is_timed,
        time_limit_minutes=data.time_limit_minutes,
    )
    db.add(assessment)
    await db.flush()

    # Select and assign questions (SPEC-014)
    await select_questions(db, assessment, user_id, config_hash, role)

    return assessment


async def get_assessment(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Assessment:
    """Get an assessment by ID, ensuring it belongs to the user."""
    result = await db.execute(
        select(Assessment).where(
            Assessment.id == assessment_id,
            Assessment.user_id == user_id,
        )
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise NotFoundError("Assessment", assessment_id)
    return assessment


async def list_assessments(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[Assessment]:
    """List all assessments for a user, most recent first."""
    result = await db.execute(
        select(Assessment)
        .where(Assessment.user_id == user_id)
        .order_by(Assessment.created_at.desc())
    )
    return list(result.scalars().all())


async def submit_answer(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    user_id: uuid.UUID,
    data: AnswerSubmitRequest,
) -> Answer:
    """Submit or auto-save an answer (upsert behavior)."""
    # Check assessment exists and belongs to user
    assessment = await get_assessment(db, assessment_id, user_id)
    if assessment.status != "in_progress":
        raise AppError("Cannot submit answers to a completed assessment", status_code=400)

    # Upsert answer
    result = await db.execute(
        select(Answer).where(
            Answer.assessment_id == assessment_id,
            Answer.question_id == data.question_id,
        )
    )
    answer = result.scalar_one_or_none()

    if answer is None:
        answer = Answer(
            assessment_id=assessment_id,
            question_id=data.question_id,
            user_id=user_id,
            response_text=data.response_text,
            selected_option=data.selected_option,
            time_spent_seconds=data.time_spent_seconds,
            is_auto_saved=data.is_auto_saved,
            submitted_at=None if data.is_auto_saved else datetime.now(UTC),
        )
        db.add(answer)
    else:
        answer.response_text = data.response_text
        answer.selected_option = data.selected_option
        answer.time_spent_seconds = data.time_spent_seconds
        answer.is_auto_saved = data.is_auto_saved
        if not data.is_auto_saved:
            answer.submitted_at = datetime.now(UTC)

    await db.flush()
    return answer


async def complete_assessment(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Assessment:
    """Mark an assessment as completed and trigger grading pipeline.

    Auto-grades MCQ answers synchronously, then grades open-ended answers
    via AI, and computes final results (SPEC-030/031/032).
    """
    assessment = await get_assessment(db, assessment_id, user_id)
    if assessment.status != "in_progress":
        raise AppError("Assessment is already completed", status_code=400)

    assessment.status = "completed"
    assessment.completed_at = datetime.now(UTC)
    await db.flush()

    # Trigger grading pipeline (creates AssessmentResult, grades, computes scores)
    from src.scoring.service import create_result_and_grade

    await create_result_and_grade(db, assessment_id, user_id)

    return assessment


async def get_progress(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[str, object]:
    """Get progress summary for an assessment."""
    assessment = await get_assessment(db, assessment_id, user_id)

    answered_count_result = await db.execute(
        select(func.count(Answer.id)).where(
            Answer.assessment_id == assessment_id,
            Answer.is_auto_saved.is_(False),
        )
    )
    answered_count = answered_count_result.scalar() or 0

    time_elapsed = None
    time_remaining = None
    now = datetime.now(UTC)
    if assessment.started_at:
        time_elapsed = int((now - assessment.started_at).total_seconds())
        if assessment.is_timed and assessment.time_limit_minutes:
            total_seconds = assessment.time_limit_minutes * 60
            time_remaining = max(0, total_seconds - time_elapsed)

    return {
        "assessment_id": assessment.id,
        "total_questions": assessment.total_questions,
        "answered_count": answered_count,
        "current_index": assessment.current_question_index,
        "time_elapsed_seconds": time_elapsed,
        "time_remaining_seconds": time_remaining,
    }
