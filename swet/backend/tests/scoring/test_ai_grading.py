"""Tests for AI grading via LLM (SPEC-031)."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.assessments.models import Answer, Assessment, AssessmentQuestion
from src.questions.models import Competency, Question, QuestionPool
from src.scoring.grader import GradeResult, _build_grading_prompt, _parse_grade_result, grade_answer
from src.scoring.models import AnswerGrade
from src.scoring.service import create_result_and_grade, grade_open_ended


def _make_grade_json(score: int = 7, max_score: int = 10) -> str:
    """Build a valid grade result JSON string."""
    return json.dumps(
        {
            "criteria_scores": [
                {
                    "name": "Correctness",
                    "score": score,
                    "max_points": max_score,
                    "feedback": "Good understanding of the concept.",
                }
            ],
            "total_score": score,
            "max_score": max_score,
            "normalized_score": score / max_score,
            "overall_feedback": "Solid answer with minor gaps.",
        }
    )


class TestBuildGradingPrompt:
    """Tests for prompt construction."""

    def test_includes_question_details(self):
        prompt = _build_grading_prompt(
            question_title="Test Title",
            question_body="Test Body",
            question_format="short_answer",
            rubric={"criteria": [{"name": "Accuracy", "max_points": 10}]},
            answer_text="My answer here",
        )
        assert "Test Title" in prompt
        assert "Test Body" in prompt
        assert "short_answer" in prompt
        assert "My answer here" in prompt
        assert "Accuracy" in prompt

    def test_includes_code_snippet_when_provided(self):
        prompt = _build_grading_prompt(
            question_title="Code Q",
            question_body="Review this code",
            question_format="code_review",
            rubric={},
            answer_text="The code has a bug",
            code_snippet="def foo(): return None",
        )
        assert "def foo(): return None" in prompt
        assert "CODE SNIPPET" in prompt

    def test_omits_code_snippet_when_none(self):
        prompt = _build_grading_prompt(
            question_title="Q",
            question_body="Body",
            question_format="short_answer",
            rubric={},
            answer_text="Answer",
            code_snippet=None,
        )
        assert "CODE SNIPPET" not in prompt


class TestParseGradeResult:
    """Tests for parsing LLM's grading output."""

    def test_parse_valid_json(self):
        raw = _make_grade_json(7, 10)
        result = _parse_grade_result(raw)
        assert isinstance(result, GradeResult)
        assert result.total_score == 7
        assert result.max_score == 10
        assert result.normalized_score == 0.7
        assert len(result.criteria_scores) == 1
        assert result.criteria_scores[0].name == "Correctness"

    def test_parse_with_markdown_fences(self):
        raw = f"```json\n{_make_grade_json(8, 10)}\n```"
        result = _parse_grade_result(raw)
        assert result.total_score == 8
        assert result.normalized_score == 0.8

    def test_parse_with_whitespace(self):
        raw = f"\n  {_make_grade_json(5, 10)}  \n"
        result = _parse_grade_result(raw)
        assert result.total_score == 5

    def test_parse_invalid_json_raises(self):
        with pytest.raises((json.JSONDecodeError, Exception)):
            _parse_grade_result("not valid json at all")

    def test_parse_multiple_criteria(self):
        raw = json.dumps(
            {
                "criteria_scores": [
                    {"name": "Accuracy", "score": 5, "max_points": 5, "feedback": "Perfect"},
                    {
                        "name": "Clarity",
                        "score": 3,
                        "max_points": 5,
                        "feedback": "Could be clearer",
                    },
                ],
                "total_score": 8,
                "max_score": 10,
                "normalized_score": 0.8,
                "overall_feedback": "Good job overall.",
            }
        )
        result = _parse_grade_result(raw)
        assert len(result.criteria_scores) == 2
        assert result.criteria_scores[0].score == 5
        assert result.criteria_scores[1].score == 3


@pytest.mark.asyncio
async def test_grade_answer_with_mock():
    """grade_answer should call LLM and parse the response."""
    mock_fn = AsyncMock(return_value=(_make_grade_json(9, 10), 100, 200))

    with patch("src.scoring.grader.chat_completion", mock_fn):
        result = await grade_answer(
            question_title="Test Q",
            question_body="Explain testing",
            question_format="short_answer",
            rubric={"criteria": [{"name": "Depth", "max_points": 10}]},
            answer_text="Testing ensures correctness...",
        )

    assert isinstance(result, GradeResult)
    assert result.total_score == 9
    assert result.normalized_score == 0.9
    mock_fn.assert_awaited_once()


@pytest.mark.asyncio
async def test_grade_answer_with_code_snippet():
    """grade_answer should include code_snippet in the prompt when provided."""
    mock_fn = AsyncMock(return_value=(_make_grade_json(6, 10), 150, 250))

    with patch("src.scoring.grader.chat_completion", mock_fn):
        result = await grade_answer(
            question_title="Review Code",
            question_body="Find the bug",
            question_format="code_review",
            rubric={},
            answer_text="The bug is in line 3",
            code_snippet="def broken():\n    x = 1/0",
        )

    assert result.total_score == 6
    # Verify the prompt included the code snippet via the kwargs
    call_kwargs = mock_fn.call_args.kwargs
    assert "def broken()" in call_kwargs["user_message"]


@pytest.fixture
async def ai_grading_db(db_session: AsyncSession):
    """Set up assessment with mixed MCQ and open-ended questions."""
    user_id = uuid.uuid4()
    comp = Competency(
        id=3, slug="design", name="Design", description="Design skills", category="core"
    )
    db_session.add(comp)
    await db_session.flush()

    pool = QuestionPool(
        config_hash="ai_hash",
        competency_id=3,
        difficulty=3,
        format="short_answer",
        total_questions=2,
        generation_status="complete",
    )
    db_session.add(pool)
    await db_session.flush()

    # 1 MCQ question
    mcq_q = Question(
        pool_id=pool.id,
        competency_id=3,
        format="mcq",
        difficulty=3,
        title="MCQ Q",
        body="Pick one",
        options={"A": "a", "B": "b", "C": "c", "D": "d"},
        correct_answer="B",
    )
    db_session.add(mcq_q)

    # 2 open-ended questions
    open_q1 = Question(
        pool_id=pool.id,
        competency_id=3,
        format="short_answer",
        difficulty=3,
        title="Open Q1",
        body="Explain design patterns",
        grading_rubric={"criteria": [{"name": "Depth", "max_points": 10}]},
    )
    db_session.add(open_q1)

    open_q2 = Question(
        pool_id=pool.id,
        competency_id=3,
        format="code_review",
        difficulty=4,
        title="Open Q2",
        body="Review this code",
        code_snippet="class Foo: pass",
        grading_rubric={"criteria": [{"name": "Analysis", "max_points": 5}]},
    )
    db_session.add(open_q2)
    await db_session.flush()

    assessment = Assessment(
        user_id=user_id, config_hash="ai_hash", status="completed", total_questions=3
    )
    db_session.add(assessment)
    await db_session.flush()

    questions = [mcq_q, open_q1, open_q2]
    for i, q in enumerate(questions):
        aq = AssessmentQuestion(
            assessment_id=assessment.id, question_id=q.id, position=i, competency_id=3
        )
        db_session.add(aq)

    # Answers
    mcq_ans = Answer(
        assessment_id=assessment.id,
        question_id=mcq_q.id,
        user_id=user_id,
        selected_option="B",
        time_spent_seconds=20,
    )
    db_session.add(mcq_ans)

    open_ans1 = Answer(
        assessment_id=assessment.id,
        question_id=open_q1.id,
        user_id=user_id,
        response_text="Design patterns are reusable solutions...",
        time_spent_seconds=120,
    )
    db_session.add(open_ans1)

    open_ans2 = Answer(
        assessment_id=assessment.id,
        question_id=open_q2.id,
        user_id=user_id,
        response_text="The code lacks proper encapsulation...",
        time_spent_seconds=90,
    )
    db_session.add(open_ans2)
    await db_session.flush()

    return {
        "db": db_session,
        "user_id": user_id,
        "assessment": assessment,
        "questions": questions,
    }


@pytest.mark.asyncio
async def test_grade_open_ended_with_mock(ai_grading_db):
    """grade_open_ended should create AI grades for non-MCQ answers."""
    db = ai_grading_db["db"]
    assessment = ai_grading_db["assessment"]
    user_id = ai_grading_db["user_id"]

    # Mock the grade_answer function to return controlled results
    mock_result = GradeResult(
        criteria_scores=[
            {"name": "Depth", "score": 7, "max_points": 10, "feedback": "Good depth."}
        ],
        total_score=7,
        max_score=10,
        normalized_score=0.7,
        overall_feedback="Solid answer.",
    )

    with patch("src.scoring.service.grade_answer", return_value=mock_result):
        await grade_open_ended(db, assessment.id, user_id)

    # Verify AI grades were created for open-ended answers
    result = await db.execute(select(AnswerGrade).where(AnswerGrade.grading_method == "ai"))
    ai_grades = list(result.scalars().all())
    assert len(ai_grades) == 2

    for grade in ai_grades:
        assert grade.score == 0.7
        assert grade.feedback == "Solid answer."
        assert grade.rubric_breakdown is not None


@pytest.mark.asyncio
async def test_grade_open_ended_skips_already_graded(ai_grading_db):
    """grade_open_ended should skip answers that already have grades."""
    db = ai_grading_db["db"]
    assessment = ai_grading_db["assessment"]
    user_id = ai_grading_db["user_id"]

    mock_result = GradeResult(
        criteria_scores=[{"name": "Test", "score": 5, "max_points": 10, "feedback": "OK"}],
        total_score=5,
        max_score=10,
        normalized_score=0.5,
        overall_feedback="Average.",
    )

    # First pass
    with patch("src.scoring.service.grade_answer", return_value=mock_result) as mock_fn:
        await grade_open_ended(db, assessment.id, user_id)
        first_call_count = mock_fn.call_count

    # Second pass should skip all (already graded)
    with patch("src.scoring.service.grade_answer", return_value=mock_result) as mock_fn:
        await grade_open_ended(db, assessment.id, user_id)
        assert mock_fn.call_count == 0

    assert first_call_count == 2  # Only 2 open-ended questions


@pytest.mark.asyncio
async def test_grade_open_ended_handles_empty_response(db_session: AsyncSession):
    """Answers with no response_text should get a 0.0 fallback grade."""
    user_id = uuid.uuid4()
    comp = Competency(id=4, slug="empty", name="Empty", description="Test", category="core")
    db_session.add(comp)
    await db_session.flush()

    pool = QuestionPool(
        config_hash="empty_hash",
        competency_id=4,
        difficulty=2,
        format="short_answer",
        total_questions=1,
        generation_status="complete",
    )
    db_session.add(pool)
    await db_session.flush()

    q = Question(
        pool_id=pool.id,
        competency_id=4,
        format="short_answer",
        difficulty=2,
        title="Empty Q",
        body="Answer this",
    )
    db_session.add(q)
    await db_session.flush()

    assessment = Assessment(
        user_id=user_id, config_hash="empty_hash", status="completed", total_questions=1
    )
    db_session.add(assessment)
    await db_session.flush()

    aq = AssessmentQuestion(
        assessment_id=assessment.id, question_id=q.id, position=0, competency_id=4
    )
    db_session.add(aq)

    # Answer with no response_text
    ans = Answer(
        assessment_id=assessment.id,
        question_id=q.id,
        user_id=user_id,
        response_text=None,
        time_spent_seconds=5,
    )
    db_session.add(ans)
    await db_session.flush()

    await grade_open_ended(db_session, assessment.id, user_id)

    result = await db_session.execute(select(AnswerGrade))
    grade = result.scalar_one()
    assert grade.score == 0.0
    assert grade.is_correct is False
    assert "No response" in grade.feedback


@pytest.mark.asyncio
async def test_grade_open_ended_handles_ai_failure(ai_grading_db):
    """If AI grading fails, a fallback grade should be created."""
    db = ai_grading_db["db"]
    assessment = ai_grading_db["assessment"]
    user_id = ai_grading_db["user_id"]

    with patch("src.scoring.service.grade_answer", side_effect=Exception("API error")):
        await grade_open_ended(db, assessment.id, user_id)

    # Should still have grades (fallback ones)
    result = await db.execute(select(AnswerGrade).where(AnswerGrade.grading_method == "ai"))
    ai_grades = list(result.scalars().all())
    assert len(ai_grades) == 2

    for grade in ai_grades:
        assert grade.score == 0.0
        assert "failed" in grade.feedback.lower() or "review" in grade.feedback.lower()


@pytest.mark.asyncio
async def test_full_grading_pipeline_mixed(ai_grading_db):
    """Full pipeline: MCQ auto-grade + AI grade + results computation."""
    db = ai_grading_db["db"]
    assessment = ai_grading_db["assessment"]
    user_id = ai_grading_db["user_id"]

    mock_result = GradeResult(
        criteria_scores=[{"name": "Quality", "score": 8, "max_points": 10, "feedback": "Great"}],
        total_score=8,
        max_score=10,
        normalized_score=0.8,
        overall_feedback="Well done.",
    )

    with patch("src.scoring.service.grade_answer", return_value=mock_result):
        result = await create_result_and_grade(db, assessment.id, user_id)

    assert result.grading_status == "complete"
    # MCQ: 1.0, Open1: 0.8, Open2: 0.8 -> avg = 2.6/3 * 100 = 86.67
    assert result.overall_score == pytest.approx(86.67, abs=0.1)
    assert result.overall_proficiency_level == 5  # expert (81+)
    assert result.proficiency_label == "expert"
    assert result.total_time_seconds == 230  # 20 + 120 + 90
