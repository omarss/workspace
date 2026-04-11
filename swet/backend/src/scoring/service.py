"""Scoring service - grading, results computation, and retrieval (SPEC-030/031/032)."""

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.assessments.models import Answer, AssessmentQuestion
from src.errors import NotFoundError
from src.questions.models import Question
from src.scoring.circuit_breaker import CircuitBreakerError, grading_breaker
from src.scoring.grader import grade_answer
from src.scoring.models import AnswerGrade, AssessmentResult, CompetencyScore

logger = logging.getLogger(__name__)


async def get_result(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AssessmentResult:
    """Get the result for a completed assessment."""
    result = await db.execute(
        select(AssessmentResult).where(
            AssessmentResult.assessment_id == assessment_id,
            AssessmentResult.user_id == user_id,
        )
    )
    assessment_result = result.scalar_one_or_none()
    if not assessment_result:
        raise NotFoundError("AssessmentResult", assessment_id)
    return assessment_result


async def get_competency_scores(
    db: AsyncSession,
    result_id: uuid.UUID,
) -> list[CompetencyScore]:
    """Get per-competency scores for a result."""
    result = await db.execute(select(CompetencyScore).where(CompetencyScore.result_id == result_id))
    return list(result.scalars().all())


async def auto_grade_mcq(
    db: AsyncSession,
    assessment_id: uuid.UUID,
) -> int:
    """Auto-grade all MCQ answers for an assessment.

    Compares selected_option against the question's correct_answer.
    Returns the number of MCQ answers graded.
    """
    # Get all MCQ answers with their questions
    result = await db.execute(
        select(Answer, Question)
        .join(AssessmentQuestion, AssessmentQuestion.question_id == Answer.question_id)
        .join(Question, Question.id == Answer.question_id)
        .where(
            Answer.assessment_id == assessment_id,
            Question.format == "mcq",
        )
    )
    rows = result.all()

    graded_count = 0
    for answer, question in rows:
        # Check if already graded
        existing = await db.execute(select(AnswerGrade).where(AnswerGrade.answer_id == answer.id))
        if existing.scalar_one_or_none():
            continue

        is_correct = (
            answer.selected_option is not None and answer.selected_option == question.correct_answer
        )

        grade = AnswerGrade(
            answer_id=answer.id,
            grading_method="auto",
            is_correct=is_correct,
            score=1.0 if is_correct else 0.0,
            feedback=f"{'Correct' if is_correct else 'Incorrect'}. The correct answer is {question.correct_answer}.",
        )
        db.add(grade)
        graded_count += 1

    await db.flush()
    return graded_count


async def grade_open_ended(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Grade all non-MCQ answers using Claude Opus (SPEC-031).

    Processes up to 5 answers concurrently using asyncio.gather.
    """
    # Get all non-MCQ answers that need grading
    result = await db.execute(
        select(Answer, Question)
        .join(AssessmentQuestion, AssessmentQuestion.question_id == Answer.question_id)
        .join(Question, Question.id == Answer.question_id)
        .where(
            Answer.assessment_id == assessment_id,
            Question.format != "mcq",
        )
    )
    rows = result.all()

    # Filter out already-graded answers
    to_grade: list[tuple[Answer, Question]] = []
    for answer, question in rows:
        existing = await db.execute(select(AnswerGrade).where(AnswerGrade.answer_id == answer.id))
        if existing.scalar_one_or_none() is None:
            to_grade.append((answer, question))

    if not to_grade:
        return

    # Process in batches of 5 concurrently
    batch_size = 5
    for i in range(0, len(to_grade), batch_size):
        batch = to_grade[i : i + batch_size]
        tasks = [_grade_single_answer(db, answer, question) for answer, question in batch]
        await asyncio.gather(*tasks, return_exceptions=True)

    await db.flush()


async def _grade_single_answer(
    db: AsyncSession,
    answer: Answer,
    question: Question,
) -> None:
    """Grade a single non-MCQ answer using Claude Opus."""
    try:
        if not answer.response_text:
            # No response provided, score as 0
            grade = AnswerGrade(
                answer_id=answer.id,
                grading_method="ai",
                is_correct=False,
                score=0.0,
                feedback="No response provided.",
            )
            db.add(grade)
            return

        rubric = question.grading_rubric or {}
        result = await grading_breaker.execute(
            grade_answer(
                question_title=question.title,
                question_body=question.body,
                question_format=question.format,
                rubric=rubric,
                answer_text=answer.response_text,
                code_snippet=question.code_snippet,
            )
        )

        grade = AnswerGrade(
            answer_id=answer.id,
            grading_method="ai",
            is_correct=None,  # AI-graded answers don't have binary correct/incorrect
            score=result.normalized_score,
            feedback=result.overall_feedback,
            rubric_breakdown={
                "criteria": [
                    {
                        "name": cs.name,
                        "score": cs.score,
                        "max_points": cs.max_points,
                        "feedback": cs.feedback,
                    }
                    for cs in result.criteria_scores
                ],
                "total_score": result.total_score,
                "max_score": result.max_score,
            },
        )
        db.add(grade)

    except CircuitBreakerError:
        logger.warning("Circuit breaker open, skipping AI grading for answer %s", answer.id)
        grade = AnswerGrade(
            answer_id=answer.id,
            grading_method="ai",
            is_correct=None,
            score=0.0,
            feedback="Grading temporarily unavailable. This answer will be reviewed later.",
        )
        db.add(grade)
    except Exception:
        logger.exception("Failed to grade answer %s", answer.id)
        # Create a fallback grade on failure
        grade = AnswerGrade(
            answer_id=answer.id,
            grading_method="ai",
            is_correct=None,
            score=0.0,
            feedback="Grading failed. This answer will be reviewed manually.",
        )
        db.add(grade)


async def create_result_and_grade(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AssessmentResult:
    """Create an AssessmentResult and trigger grading pipeline.

    Called when an assessment is completed. Auto-grades MCQ synchronously,
    then spawns background AI grading for open-ended questions.
    """
    # Create the result record
    assessment_result = AssessmentResult(
        assessment_id=assessment_id,
        user_id=user_id,
        grading_status="grading",
    )
    db.add(assessment_result)
    await db.flush()

    # Auto-grade MCQ answers synchronously
    mcq_count = await auto_grade_mcq(db, assessment_id)
    logger.info("Auto-graded %d MCQ answers for assessment %s", mcq_count, assessment_id)

    # Grade open-ended answers (this may take a while with AI calls)
    await grade_open_ended(db, assessment_id, user_id)

    # Compute final results
    await compute_results(db, assessment_result, assessment_id)

    return assessment_result


def compute_proficiency_label(score: float) -> tuple[int, str]:
    """Map a 0-100 score to proficiency level and label."""
    if score >= 81:
        return 5, "expert"
    if score >= 61:
        return 4, "advanced"
    if score >= 41:
        return 3, "intermediate"
    if score >= 21:
        return 2, "beginner"
    return 1, "novice"


async def compute_results(
    db: AsyncSession,
    assessment_result: AssessmentResult,
    assessment_id: uuid.UUID,
) -> None:
    """Compute per-competency and overall scores after all grading is done (SPEC-032)."""
    # Get all answers with their grades and competency info
    result = await db.execute(
        select(Answer, AnswerGrade, AssessmentQuestion)
        .join(AnswerGrade, AnswerGrade.answer_id == Answer.id)
        .join(
            AssessmentQuestion,
            (AssessmentQuestion.assessment_id == Answer.assessment_id)
            & (AssessmentQuestion.question_id == Answer.question_id),
        )
        .where(Answer.assessment_id == assessment_id)
    )
    rows = result.all()

    # Group by competency
    competency_data: dict[int, list[tuple[Answer, AnswerGrade]]] = {}
    for answer, grade, aq in rows:
        comp_id = aq.competency_id
        if comp_id not in competency_data:
            competency_data[comp_id] = []
        competency_data[comp_id].append((answer, grade))

    # Compute per-competency scores
    total_weighted_score = 0.0
    total_questions = 0

    for comp_id, answer_grades in competency_data.items():
        comp_total = len(answer_grades)
        if comp_total == 0:
            continue

        # Compute AI-graded average for the CompetencyScore record
        ai_scores = [g.score for _, g in answer_grades if g.grading_method == "ai"]
        ai_avg = sum(ai_scores) / len(ai_scores) if ai_scores else None

        # Weighted average of MCQ and AI scores
        total_score = sum(g.score for _, g in answer_grades)
        comp_score = (total_score / comp_total) * 100

        correct_count = sum(1 for _, g in answer_grades if g.is_correct is True)
        level, _ = compute_proficiency_label(comp_score)

        # Create or update CompetencyScore
        cs = CompetencyScore(
            result_id=assessment_result.id,
            competency_id=comp_id,
            score=comp_score,
            proficiency_level=level,
            questions_total=comp_total,
            questions_correct=correct_count,
            ai_graded_avg=ai_avg,
        )
        db.add(cs)

        total_weighted_score += total_score
        total_questions += comp_total

    # Compute overall score
    overall_score = (total_weighted_score / total_questions * 100) if total_questions > 0 else 0.0
    overall_level, overall_label = compute_proficiency_label(overall_score)

    # Compute total time
    time_result = await db.execute(
        select(func.sum(Answer.time_spent_seconds)).where(Answer.assessment_id == assessment_id)
    )
    total_time = time_result.scalar() or 0

    # Update the assessment result
    assessment_result.overall_score = overall_score
    assessment_result.overall_proficiency_level = overall_level
    assessment_result.proficiency_label = overall_label
    assessment_result.total_time_seconds = total_time
    assessment_result.grading_status = "complete"

    await db.flush()
    logger.info(
        "Computed results for assessment result %s: score=%.1f, level=%s",
        assessment_result.id,
        overall_score,
        overall_label,
    )


async def get_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    page: int = 1,
    per_page: int = 10,
    status: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> tuple[list[AssessmentResult], int]:
    """Get paginated assessment result history for a user."""
    query = select(AssessmentResult).where(AssessmentResult.user_id == user_id)

    if status:
        query = query.where(AssessmentResult.grading_status == status)
    if from_date:
        query = query.where(AssessmentResult.created_at >= from_date)
    if to_date:
        query = query.where(AssessmentResult.created_at <= to_date)

    # Count total matching results
    count_query = select(func.count(AssessmentResult.id)).where(AssessmentResult.user_id == user_id)
    if status:
        count_query = count_query.where(AssessmentResult.grading_status == status)
    if from_date:
        count_query = count_query.where(AssessmentResult.created_at >= from_date)
    if to_date:
        count_query = count_query.where(AssessmentResult.created_at <= to_date)

    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    # Fetch paginated results
    offset = (page - 1) * per_page
    query = query.order_by(AssessmentResult.created_at.desc()).offset(offset).limit(per_page)

    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total_count


async def get_history_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, object]:
    """Get summary statistics for a user's assessment history."""
    result = await db.execute(
        select(
            func.count(AssessmentResult.id).label("total"),
            func.avg(AssessmentResult.overall_score).label("avg_score"),
            func.max(AssessmentResult.overall_score).label("max_score"),
        ).where(
            AssessmentResult.user_id == user_id,
            AssessmentResult.grading_status == "complete",
        )
    )
    row = result.one()

    # Get latest proficiency label
    latest_result = await db.execute(
        select(AssessmentResult.proficiency_label)
        .where(
            AssessmentResult.user_id == user_id,
            AssessmentResult.grading_status == "complete",
        )
        .order_by(AssessmentResult.created_at.desc())
        .limit(1)
    )
    latest_label = latest_result.scalar() or "novice"

    return {
        "total_assessments": row.total or 0,
        "average_score": round(float(row.avg_score or 0), 2),
        "highest_score": round(float(row.max_score or 0), 2),
        "latest_proficiency_label": latest_label,
    }


async def get_trend_data(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[dict[str, object]]:
    """Get score trend data points ordered chronologically."""
    result = await db.execute(
        select(AssessmentResult.created_at, AssessmentResult.overall_score)
        .where(
            AssessmentResult.user_id == user_id,
            AssessmentResult.grading_status == "complete",
        )
        .order_by(AssessmentResult.created_at.asc())
    )
    return [{"date": row.created_at, "score": row.overall_score} for row in result.all()]
