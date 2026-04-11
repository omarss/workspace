"""Tests for MCQ auto-grading (SPEC-030)."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.assessments.models import Answer, Assessment, AssessmentQuestion
from src.questions.models import Competency, Question, QuestionPool
from src.scoring.models import AnswerGrade, AssessmentResult
from src.scoring.service import auto_grade_mcq, compute_proficiency_label, create_result_and_grade


@pytest.fixture
async def grading_db(db_session: AsyncSession):
    """Set up a complete assessment scenario for grading tests.

    Creates:
    - 1 competency
    - 1 question pool with 3 MCQ questions (1 correct answer each)
    - 1 assessment with 3 answers (2 correct, 1 wrong)
    """
    user_id = uuid.uuid4()
    comp = Competency(
        id=1, slug="testing", name="Testing", description="Test competency", category="core"
    )
    db_session.add(comp)
    await db_session.flush()

    pool = QuestionPool(
        config_hash="test_hash",
        competency_id=1,
        difficulty=3,
        format="mcq",
        total_questions=3,
        generation_status="complete",
    )
    db_session.add(pool)
    await db_session.flush()

    # Create 3 MCQ questions with known correct answers
    questions = []
    for i, correct in enumerate(["A", "B", "C"]):
        q = Question(
            pool_id=pool.id,
            competency_id=1,
            format="mcq",
            difficulty=3,
            title=f"MCQ Question {i + 1}",
            body=f"What is the answer to question {i + 1}?",
            options={"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
            correct_answer=correct,
        )
        db_session.add(q)
        questions.append(q)

    await db_session.flush()

    # Create assessment
    assessment = Assessment(
        user_id=user_id,
        config_hash="test_hash",
        status="completed",
        total_questions=3,
    )
    db_session.add(assessment)
    await db_session.flush()

    # Create assessment-question links
    for i, q in enumerate(questions):
        aq = AssessmentQuestion(
            assessment_id=assessment.id,
            question_id=q.id,
            position=i,
            competency_id=1,
        )
        db_session.add(aq)

    # Create answers: Q1 correct (A), Q2 correct (B), Q3 wrong (A instead of C)
    answers_data = [("A", True), ("B", True), ("A", False)]
    answers = []
    for i, (selected, _expected) in enumerate(answers_data):
        ans = Answer(
            assessment_id=assessment.id,
            question_id=questions[i].id,
            user_id=user_id,
            selected_option=selected,
            time_spent_seconds=30,
        )
        db_session.add(ans)
        answers.append(ans)

    await db_session.flush()

    return {
        "db": db_session,
        "user_id": user_id,
        "assessment": assessment,
        "questions": questions,
        "answers": answers,
    }


@pytest.mark.asyncio
async def test_auto_grade_mcq_correct_and_incorrect(grading_db):
    """Auto-grading should score correct answers as 1.0 and incorrect as 0.0."""
    db = grading_db["db"]
    assessment = grading_db["assessment"]

    graded_count = await auto_grade_mcq(db, assessment.id)
    assert graded_count == 3

    # Verify grades created
    result = await db.execute(select(AnswerGrade).order_by(AnswerGrade.graded_at))
    grades = list(result.scalars().all())
    assert len(grades) == 3

    # First two should be correct, third should be wrong
    assert grades[0].is_correct is True
    assert grades[0].score == 1.0
    assert grades[0].grading_method == "auto"
    assert "Correct" in grades[0].feedback

    assert grades[1].is_correct is True
    assert grades[1].score == 1.0

    assert grades[2].is_correct is False
    assert grades[2].score == 0.0
    assert "Incorrect" in grades[2].feedback
    assert "C" in grades[2].feedback  # Should mention the correct answer


@pytest.mark.asyncio
async def test_auto_grade_mcq_idempotent(grading_db):
    """Running auto_grade_mcq twice should not create duplicate grades."""
    db = grading_db["db"]
    assessment = grading_db["assessment"]

    first_count = await auto_grade_mcq(db, assessment.id)
    assert first_count == 3

    second_count = await auto_grade_mcq(db, assessment.id)
    assert second_count == 0  # All already graded

    # Verify no duplicates
    result = await db.execute(select(AnswerGrade))
    grades = list(result.scalars().all())
    assert len(grades) == 3


@pytest.mark.asyncio
async def test_auto_grade_mcq_no_selected_option(db_session: AsyncSession):
    """An answer with no selected_option should be scored as incorrect."""
    user_id = uuid.uuid4()
    comp = Competency(id=2, slug="test2", name="Test2", description="Test", category="core")
    db_session.add(comp)
    await db_session.flush()

    pool = QuestionPool(
        config_hash="hash2",
        competency_id=2,
        difficulty=3,
        format="mcq",
        total_questions=1,
        generation_status="complete",
    )
    db_session.add(pool)
    await db_session.flush()

    q = Question(
        pool_id=pool.id,
        competency_id=2,
        format="mcq",
        difficulty=3,
        title="Unanswered",
        body="No answer given",
        options={"A": "a", "B": "b", "C": "c", "D": "d"},
        correct_answer="A",
    )
    db_session.add(q)
    await db_session.flush()

    assessment = Assessment(
        user_id=user_id, config_hash="hash2", status="completed", total_questions=1
    )
    db_session.add(assessment)
    await db_session.flush()

    aq = AssessmentQuestion(
        assessment_id=assessment.id, question_id=q.id, position=0, competency_id=2
    )
    db_session.add(aq)

    # Answer with no selected_option
    ans = Answer(
        assessment_id=assessment.id,
        question_id=q.id,
        user_id=user_id,
        selected_option=None,
        time_spent_seconds=5,
    )
    db_session.add(ans)
    await db_session.flush()

    graded = await auto_grade_mcq(db_session, assessment.id)
    assert graded == 1

    result = await db_session.execute(select(AnswerGrade))
    grade = result.scalar_one()
    assert grade.is_correct is False
    assert grade.score == 0.0


class TestComputeProficiencyLabel:
    """Tests for the proficiency label mapping function."""

    def test_expert_threshold(self):
        level, label = compute_proficiency_label(81.0)
        assert level == 5
        assert label == "expert"

    def test_advanced_threshold(self):
        level, label = compute_proficiency_label(61.0)
        assert level == 4
        assert label == "advanced"

    def test_intermediate_threshold(self):
        level, label = compute_proficiency_label(41.0)
        assert level == 3
        assert label == "intermediate"

    def test_beginner_threshold(self):
        level, label = compute_proficiency_label(21.0)
        assert level == 2
        assert label == "beginner"

    def test_novice_threshold(self):
        level, label = compute_proficiency_label(20.0)
        assert level == 1
        assert label == "novice"

    def test_zero_score(self):
        level, label = compute_proficiency_label(0.0)
        assert level == 1
        assert label == "novice"

    def test_perfect_score(self):
        level, label = compute_proficiency_label(100.0)
        assert level == 5
        assert label == "expert"

    def test_boundary_80(self):
        """80 is advanced, not expert."""
        level, label = compute_proficiency_label(80.0)
        assert level == 4
        assert label == "advanced"


@pytest.mark.asyncio
async def test_create_result_and_grade_mcq_only(grading_db):
    """Full grading pipeline with MCQ-only assessment should compute results correctly."""
    db = grading_db["db"]
    assessment = grading_db["assessment"]
    user_id = grading_db["user_id"]

    result = await create_result_and_grade(db, assessment.id, user_id)

    assert isinstance(result, AssessmentResult)
    assert result.grading_status == "complete"
    # 2 correct out of 3 = 66.67% score
    assert result.overall_score == pytest.approx(66.67, abs=0.1)
    assert result.overall_proficiency_level == 4  # advanced (61-80)
    assert result.proficiency_label == "advanced"
    assert result.total_time_seconds == 90  # 3 * 30s
