"""Tests for grading logic."""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from swet_cli.grader import _parse_grade_response, grade_mcq


def test_grade_mcq_correct():
    """MCQ correct answer scores 1.0."""
    result = grade_mcq("B", "B")
    assert result.normalized_score == 1.0
    assert result.total_score == 1


def test_grade_mcq_incorrect():
    """MCQ wrong answer scores 0.0."""
    result = grade_mcq("A", "B")
    assert result.normalized_score == 0.0
    assert result.total_score == 0


def test_grade_mcq_case_insensitive():
    """MCQ grading is case-insensitive."""
    result = grade_mcq("b", "B")
    assert result.normalized_score == 1.0


def test_parse_grade_response():
    """Parse a valid grading JSON response."""
    raw = """{
        "criteria_scores": [
            {"name": "Accuracy", "score": 7, "max_points": 10, "feedback": "Good"}
        ],
        "total_score": 7,
        "max_score": 10,
        "normalized_score": 0.7,
        "overall_feedback": "Well done"
    }"""
    result = _parse_grade_response(raw)
    assert result.total_score == 7
    assert result.normalized_score == 0.7
    assert len(result.criteria_scores) == 1


def test_parse_grade_response_with_fences():
    """Parse grading response with markdown fences."""
    raw = """```json
    {
        "criteria_scores": [
            {"name": "Test", "score": 5, "max_points": 10, "feedback": "OK"}
        ],
        "total_score": 5,
        "max_score": 10,
        "normalized_score": 0.5,
        "overall_feedback": "Average"
    }
    ```"""
    result = _parse_grade_response(raw)
    assert result.total_score == 5
