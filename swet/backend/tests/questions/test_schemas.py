"""Tests for question format validation schemas (SPEC-015)."""

import pytest
from pydantic import ValidationError

from src.questions.schemas import (
    CodeBasedQuestionData,
    GeneratedQuestion,
    GradingRubric,
    MCQQuestionData,
    QuestionMetadata,
    RubricCriterion,
)

# ---------------------------------------------------------------------------
# RubricCriterion
# ---------------------------------------------------------------------------


class TestRubricCriterion:
    def test_valid_criterion(self):
        c = RubricCriterion(
            name="Test",
            description="Test desc",
            max_points=3,
            key_indicators=["indicator 1"],
        )
        assert c.name == "Test"
        assert c.max_points == 3

    def test_rejects_zero_max_points(self):
        with pytest.raises(ValidationError):
            RubricCriterion(name="Test", description="desc", max_points=0, key_indicators=["x"])

    def test_rejects_empty_key_indicators(self):
        with pytest.raises(ValidationError):
            RubricCriterion(name="Test", description="desc", max_points=3, key_indicators=[])


# ---------------------------------------------------------------------------
# GradingRubric
# ---------------------------------------------------------------------------


class TestGradingRubric:
    def _make_rubric(self, criteria_points: list[int], max_score: int) -> GradingRubric:
        criteria = [
            RubricCriterion(
                name=f"Criterion {i}",
                description=f"Description {i}",
                max_points=pts,
                key_indicators=[f"indicator {i}"],
            )
            for i, pts in enumerate(criteria_points)
        ]
        return GradingRubric(
            criteria=criteria, max_score=max_score, passing_threshold=max_score // 2
        )

    def test_valid_rubric(self):
        rubric = self._make_rubric([4, 3, 3], max_score=10)
        assert rubric.max_score == 10
        assert len(rubric.criteria) == 3

    def test_rejects_mismatched_score(self):
        """max_score must equal sum of criteria max_points."""
        with pytest.raises(ValidationError, match="must equal max_score"):
            self._make_rubric([4, 3, 3], max_score=15)

    def test_rejects_empty_criteria(self):
        with pytest.raises(ValidationError):
            GradingRubric(criteria=[], max_score=10, passing_threshold=5)


# ---------------------------------------------------------------------------
# MCQQuestionData
# ---------------------------------------------------------------------------


class TestMCQQuestionData:
    def test_valid_mcq(self):
        data = MCQQuestionData(
            options={"A": "opt1", "B": "opt2", "C": "opt3", "D": "opt4"},
            correct_answer="B",
        )
        assert data.correct_answer == "B"

    def test_rejects_missing_option(self):
        with pytest.raises(ValidationError, match="exactly options A, B, C, D"):
            MCQQuestionData(
                options={"A": "opt1", "B": "opt2", "C": "opt3"},
                correct_answer="A",
            )

    def test_rejects_extra_option(self):
        with pytest.raises(ValidationError, match="exactly options A, B, C, D"):
            MCQQuestionData(
                options={"A": "a", "B": "b", "C": "c", "D": "d", "E": "e"},
                correct_answer="A",
            )

    def test_rejects_invalid_correct_answer(self):
        with pytest.raises(ValidationError):
            MCQQuestionData(
                options={"A": "a", "B": "b", "C": "c", "D": "d"},
                correct_answer="E",
            )


# ---------------------------------------------------------------------------
# CodeBasedQuestionData
# ---------------------------------------------------------------------------


class TestCodeBasedQuestionData:
    def test_valid_code_question(self):
        data = CodeBasedQuestionData(
            code_snippet="def hello():\n    return 'world'",
            language="python",
            grading_rubric=GradingRubric(
                criteria=[
                    RubricCriterion(
                        name="Analysis",
                        description="Code analysis",
                        max_points=10,
                        key_indicators=["finds bugs"],
                    )
                ],
                max_score=10,
                passing_threshold=5,
            ),
        )
        assert data.language == "python"

    def test_rejects_short_code_snippet(self):
        with pytest.raises(ValidationError):
            CodeBasedQuestionData(
                code_snippet="x=1",
                language="python",
                grading_rubric=GradingRubric(
                    criteria=[
                        RubricCriterion(
                            name="A", description="d", max_points=1, key_indicators=["x"]
                        )
                    ],
                    max_score=1,
                    passing_threshold=0,
                ),
            )

    def test_rejects_empty_language(self):
        with pytest.raises(ValidationError):
            CodeBasedQuestionData(
                code_snippet="def hello():\n    return 'world'",
                language="",
                grading_rubric=GradingRubric(
                    criteria=[
                        RubricCriterion(
                            name="A", description="d", max_points=1, key_indicators=["x"]
                        )
                    ],
                    max_score=1,
                    passing_threshold=0,
                ),
            )


# ---------------------------------------------------------------------------
# QuestionMetadata
# ---------------------------------------------------------------------------


class TestQuestionMetadata:
    def test_valid_metadata(self):
        m = QuestionMetadata(topics=["security", "jwt"], estimated_time_minutes=5)
        assert m.estimated_time_minutes == 5

    def test_default_values(self):
        m = QuestionMetadata()
        assert m.topics == []
        assert m.estimated_time_minutes == 1

    def test_rejects_zero_time(self):
        with pytest.raises(ValidationError):
            QuestionMetadata(estimated_time_minutes=0)


# ---------------------------------------------------------------------------
# GeneratedQuestion (full format validation)
# ---------------------------------------------------------------------------


class TestGeneratedQuestion:
    """Test the top-level schema that validates Claude's output."""

    def _make_rubric_dict(self) -> dict:
        return {
            "criteria": [
                {
                    "name": "Analysis",
                    "description": "Quality of analysis",
                    "max_points": 10,
                    "key_indicators": ["identifies issues"],
                }
            ],
            "max_score": 10,
            "passing_threshold": 5,
        }

    def test_valid_mcq(self):
        q = GeneratedQuestion(
            format="mcq",
            title="What is dependency injection?",
            body="Choose the best answer describing DI...",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            correct_answer="A",
            explanation="DI is a design pattern that...",
        )
        assert q.format == "mcq"

    def test_valid_code_review(self):
        q = GeneratedQuestion(
            format="code_review",
            title="Review this authentication middleware",
            body="Review the following code for issues...",
            code_snippet="class Auth:\n    def __init__(self):\n        pass",
            language="python",
            grading_rubric=self._make_rubric_dict(),
            explanation="Key issues include...",
        )
        assert q.format == "code_review"

    def test_valid_debugging(self):
        q = GeneratedQuestion(
            format="debugging",
            title="Debug this connection pool issue",
            body="Find the root cause and fix...",
            code_snippet="async def get_user():\n    conn = await pool.acquire()",
            language="python",
            grading_rubric=self._make_rubric_dict(),
            explanation="The root cause is...",
        )
        assert q.format == "debugging"

    def test_valid_short_answer(self):
        q = GeneratedQuestion(
            format="short_answer",
            title="Explain the CAP theorem",
            body="Describe each guarantee and provide examples...",
            grading_rubric=self._make_rubric_dict(),
            explanation="The CAP theorem states...",
        )
        assert q.format == "short_answer"

    def test_valid_design_prompt(self):
        q = GeneratedQuestion(
            format="design_prompt",
            title="Design a notification system",
            body="Design a system for 50M DAU supporting push, in-app, and email...",
            grading_rubric=self._make_rubric_dict(),
            explanation="A well-designed system requires...",
        )
        assert q.format == "design_prompt"

    def test_rejects_invalid_format(self):
        with pytest.raises(ValidationError, match="Invalid format"):
            GeneratedQuestion(
                format="essay",
                title="Some title here",
                body="Some body text here",
                explanation="Some explanation here",
            )

    def test_mcq_requires_options(self):
        with pytest.raises(ValidationError, match="require 'options'"):
            GeneratedQuestion(
                format="mcq",
                title="What is dependency injection?",
                body="Choose the best answer...",
                correct_answer="A",
                explanation="DI is a design pattern...",
            )

    def test_mcq_requires_correct_answer(self):
        with pytest.raises(ValidationError, match="require 'options'"):
            GeneratedQuestion(
                format="mcq",
                title="What is dependency injection?",
                body="Choose the best answer...",
                options={"A": "a", "B": "b", "C": "c", "D": "d"},
                explanation="DI is a design pattern...",
            )

    def test_code_review_requires_code_snippet(self):
        with pytest.raises(ValidationError, match="require 'code_snippet'"):
            GeneratedQuestion(
                format="code_review",
                title="Review this authentication middleware",
                body="Review the following code...",
                language="python",
                grading_rubric=self._make_rubric_dict(),
                explanation="Key issues include...",
            )

    def test_debugging_requires_language(self):
        with pytest.raises(ValidationError, match="require 'code_snippet'"):
            GeneratedQuestion(
                format="debugging",
                title="Debug this connection pool issue",
                body="Find the root cause...",
                code_snippet="async def get_user():\n    conn = await pool.acquire()",
                grading_rubric=self._make_rubric_dict(),
                explanation="The root cause is...",
            )

    def test_short_answer_requires_rubric(self):
        with pytest.raises(ValidationError, match="require 'grading_rubric'"):
            GeneratedQuestion(
                format="short_answer",
                title="Explain the CAP theorem",
                body="Describe each guarantee...",
                explanation="The CAP theorem states...",
            )

    def test_design_prompt_requires_rubric(self):
        with pytest.raises(ValidationError, match="require 'grading_rubric'"):
            GeneratedQuestion(
                format="design_prompt",
                title="Design a notification system",
                body="Design a system for 50M DAU...",
                explanation="A well-designed system...",
            )

    def test_mcq_validates_option_keys(self):
        """MCQ cross-validation catches bad option keys."""
        with pytest.raises(ValidationError):
            GeneratedQuestion(
                format="mcq",
                title="What is dependency injection?",
                body="Choose the best answer...",
                options={"A": "a", "B": "b", "C": "c"},  # Missing D
                correct_answer="A",
                explanation="DI is a design pattern...",
            )
