"""Attempt service: grading, adaptive updates, and review enqueueing."""

from swet_api.db import (
    auto_enqueue_review,
    get_user_question,
    save_user_attempt,
    update_user_format_performance,
    update_user_streak,
)
from swet_api.engine import update_adaptive_level
from swet_api.schemas import AnswerRequest, GradeResponse
from swet_cli.grader import grade_mcq, grade_open_ended
from swet_cli.models import GradeResult


def grade_and_save(user_id: str, req: AnswerRequest) -> tuple[GradeResponse, dict]:
    """Grade an answer, save the attempt, and update all adaptive state.

    Returns (GradeResponse, question_dict) for the router to use.
    Raises ValueError if the question is not found or lacks grading data.
    """
    question = get_user_question(user_id, req.question_id)
    if question is None:
        raise ValueError("Question not found")

    grade = _grade_question(question, req.answer_text)

    attempt_id = save_user_attempt(
        user_id=user_id,
        question_id=req.question_id,
        answer_text=req.answer_text,
        score=grade.normalized_score,
        max_score=grade.max_score,
        total_score=grade.total_score,
        grade_details=grade.model_dump(),
        feedback=grade.overall_feedback,
        time_seconds=req.time_seconds,
        confidence=req.confidence,
    )

    q_format = question["format"]
    update_adaptive_level(user_id, question["competency_slug"], grade.normalized_score, question["difficulty"])
    update_user_format_performance(user_id, question["competency_slug"], q_format, grade.normalized_score)
    update_user_streak(user_id)
    auto_enqueue_review(user_id, req.question_id, grade.normalized_score)

    response = _build_grade_response(attempt_id, grade, question)
    return response, question


def _grade_question(question: dict, answer_text: str) -> GradeResult:
    """Grade an answer using MCQ or open-ended grading."""
    q_format = question["format"]
    if q_format == "mcq":
        if not question.get("correct_answer"):
            raise ValueError("Question has no correct answer")
        return grade_mcq(answer_text, question["correct_answer"])

    if not question.get("grading_rubric"):
        raise ValueError("Question has no grading rubric")
    return grade_open_ended(
        question_title=question["title"],
        question_body=question["body"],
        question_format=q_format,
        rubric=question["grading_rubric"],
        answer_text=answer_text,
        code_snippet=question.get("code_snippet"),
    )


def _build_grade_response(attempt_id: str, grade: GradeResult, question: dict) -> GradeResponse:
    """Build a GradeResponse from grading results."""
    return GradeResponse(
        attempt_id=attempt_id,
        score=grade.total_score,
        max_score=grade.max_score,
        total_score=grade.total_score,
        normalized_score=grade.normalized_score,
        criteria_scores=[
            {
                "criterion": cs.name,
                "score": cs.score,
                "max_score": cs.max_points,
                "feedback": cs.feedback,
            }
            for cs in grade.criteria_scores
        ],
        overall_feedback=grade.overall_feedback,
        explanation=question.get("explanation"),
        correct_answer=question.get("correct_answer"),
    )
