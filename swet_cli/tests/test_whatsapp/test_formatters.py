"""Tests for WhatsApp message formatters."""

import os

# Set env vars before imports
os.environ.setdefault("SWET_WHATSAPP_ACCOUNT_SID", "test-sid")
os.environ.setdefault("SWET_WHATSAPP_AUTH_TOKEN", "test-token")
os.environ.setdefault("SWET_WHATSAPP_PHONE_NUMBER", "whatsapp:+1234567890")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from swet_cli.models import CriterionScore, GradeResult  # noqa: E402
from swet_whatsapp.formatters import (  # noqa: E402
    MAX_MESSAGE_LENGTH,
    _split_message,
    format_assessment_results,
    format_bookmarks,
    format_competencies,
    format_grade,
    format_history,
    format_level_progress,
    format_preferences,
    format_question,
    format_session_summary,
    format_stats,
    format_streak,
)

# --- _split_message ---


def test_split_short_message():
    text = "Hello, World!"
    parts = _split_message(text)
    assert len(parts) == 1
    assert parts[0] == text


def test_split_long_message():
    # Create a message longer than MAX_MESSAGE_LENGTH
    text = "A" * (MAX_MESSAGE_LENGTH + 100)
    parts = _split_message(text)
    assert len(parts) >= 2
    assert all(len(p) <= MAX_MESSAGE_LENGTH for p in parts)


def test_split_on_paragraph():
    part1 = "A" * 2000
    part2 = "B" * 2000
    text = f"{part1}\n\n{part2}"
    parts = _split_message(text, max_len=2500)
    assert len(parts) == 2


def test_split_message_limit_is_4096():
    """WhatsApp uses the same 4096 char limit."""
    assert MAX_MESSAGE_LENGTH == 4096


# --- format_question ---


def test_format_question_mcq():
    question = {
        "competency_slug": "programming_fundamentals",
        "difficulty": 3,
        "format": "mcq",
        "title": "Test Question",
        "body": "What is 1+1?",
        "code_snippet": None,
        "language": None,
        "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "correct_answer": "B",
        "metadata": None,
    }
    parts = format_question(question)
    assert len(parts) >= 1
    text = "\n".join(parts)
    # WhatsApp bold uses *text*
    assert "*SWET Question*" in text
    assert "*Test Question*" in text


def test_format_question_mcq_inline_options():
    """MCQ should render options inline with A/B/C/D labels and reply prompt."""
    question = {
        "competency_slug": "programming_fundamentals",
        "difficulty": 3,
        "format": "mcq",
        "title": "Test Question",
        "body": "What is 1+1?",
        "code_snippet": None,
        "language": None,
        "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "correct_answer": "B",
        "metadata": None,
    }
    parts = format_question(question)
    text = "\n".join(parts)
    # Options should be listed with labels (iterating dict keys: A, B, C, D)
    assert "A." in text
    assert "B." in text
    assert "C." in text
    assert "D." in text
    # Should prompt the user to reply with a letter
    assert "Reply with A, B, C, or D" in text


def test_format_question_with_code():
    question = {
        "competency_slug": "programming_fundamentals",
        "difficulty": 2,
        "format": "debugging",
        "title": "Debug This",
        "body": "Find the bug:",
        "code_snippet": "def foo():\n    return 1 + '2'",
        "language": "python",
        "options": None,
        "correct_answer": None,
        "metadata": None,
    }
    parts = format_question(question)
    text = "\n".join(parts)
    # WhatsApp uses ```code blocks```
    assert "```" in text
    assert "return 1" in text


def test_format_question_open_ended_prompt():
    """Non-MCQ questions should prompt user to type their answer."""
    question = {
        "competency_slug": "programming_fundamentals",
        "difficulty": 3,
        "format": "short_answer",
        "title": "Explain This",
        "body": "Explain polymorphism.",
        "code_snippet": None,
        "language": None,
        "options": None,
        "correct_answer": None,
        "metadata": None,
    }
    parts = format_question(question)
    text = "\n".join(parts)
    assert "Type your answer below" in text


def test_format_question_respects_limit():
    """Even very long questions should be split."""
    question = {
        "competency_slug": "programming_fundamentals",
        "difficulty": 3,
        "format": "short_answer",
        "title": "Long Question",
        "body": "X" * 5000,
        "code_snippet": None,
        "language": None,
        "options": None,
        "correct_answer": None,
        "metadata": None,
    }
    parts = format_question(question)
    assert all(len(p) <= MAX_MESSAGE_LENGTH for p in parts)


# --- format_grade ---


def test_format_grade_mcq_correct():
    grade = GradeResult(
        criteria_scores=[],
        total_score=1.0,
        max_score=1,
        normalized_score=1.0,
        overall_feedback="Correct!",
    )
    question = {"format": "mcq", "correct_answer": "B", "explanation": "Simple math."}
    text = format_grade(grade, question)
    assert "\u2713" in text  # checkmark
    assert "Correct" in text


def test_format_grade_mcq_incorrect():
    grade = GradeResult(
        criteria_scores=[],
        total_score=0.0,
        max_score=1,
        normalized_score=0.0,
        overall_feedback="Wrong.",
    )
    question = {"format": "mcq", "correct_answer": "B", "explanation": None}
    text = format_grade(grade, question)
    assert "\u2717" in text  # cross
    assert "B" in text  # correct answer shown


def test_format_grade_mcq_uses_whatsapp_bold():
    """Grade output should use *bold* not <b>."""
    grade = GradeResult(
        criteria_scores=[],
        total_score=1.0,
        max_score=1,
        normalized_score=1.0,
        overall_feedback="Correct!",
    )
    question = {"format": "mcq", "correct_answer": "A", "explanation": None}
    text = format_grade(grade, question)
    # Should use WhatsApp *bold* markers, not HTML
    assert "<b>" not in text
    assert "*" in text


def test_format_grade_open_ended():
    grade = GradeResult(
        criteria_scores=[
            CriterionScore(name="Correctness", score=8, max_points=10, feedback="Good"),
            CriterionScore(name="Style", score=7, max_points=10, feedback="OK"),
        ],
        total_score=15.0,
        max_score=20,
        normalized_score=0.75,
        overall_feedback="Solid answer.",
    )
    question = {"format": "short_answer", "correct_answer": None, "explanation": "Explanation text."}
    text = format_grade(grade, question)
    assert "15/20" in text
    assert "75%" in text
    assert "Correctness" in text
    assert "Style" in text


def test_format_grade_with_time():
    grade = GradeResult(
        criteria_scores=[],
        total_score=1.0,
        max_score=1,
        normalized_score=1.0,
        overall_feedback="OK",
    )
    text = format_grade(grade, {"format": "mcq", "correct_answer": "A", "explanation": None}, time_seconds=95.0)
    assert "1m 35s" in text


# --- format_streak ---


def test_format_streak_new():
    assert "Day 1" in format_streak(1, True)


def test_format_streak_ongoing():
    assert "Day 5 streak" in format_streak(5, True)


def test_format_streak_same_day():
    assert "Current streak" in format_streak(3, False)


# --- format_level_progress ---


def test_format_level_up():
    text = format_level_progress("programming_fundamentals", 2, 3)
    assert "Level up" in text


def test_format_level_down():
    text = format_level_progress("programming_fundamentals", 3, 2)
    assert "adjusted" in text


def test_format_level_progress_uses_whatsapp_bold():
    """Level progress should use *bold* not HTML."""
    text = format_level_progress("programming_fundamentals", 2, 3)
    assert "<b>" not in text
    assert "*" in text


# --- format_stats ---


def test_format_stats_empty():
    text = format_stats([])
    assert "No graded attempts" in text


def test_format_stats_with_data():
    stats = [
        {
            "competency_slug": "programming_fundamentals",
            "total_attempts": 10,
            "avg_score": 0.75,
            "min_score": 0.5,
            "max_score": 1.0,
        }
    ]
    text = format_stats(stats, streak=5, longest_streak=10)
    assert "75%" in text
    assert "5" in text


def test_format_stats_uses_whatsapp_bold():
    """Stats should use *bold* not HTML."""
    stats = [
        {
            "competency_slug": "programming_fundamentals",
            "total_attempts": 10,
            "avg_score": 0.75,
            "min_score": 0.5,
            "max_score": 1.0,
        }
    ]
    text = format_stats(stats)
    assert "<b>" not in text
    assert "*Stats by Competency*" in text


# --- format_history ---


def test_format_history_empty():
    text = format_history([])
    assert "No attempts" in text


def test_format_history_with_data():
    history = [
        {
            "title": "Test Question",
            "competency_slug": "programming_fundamentals",
            "format": "mcq",
            "difficulty": 3,
            "score": 1.0,
            "time_seconds": None,
            "completed_at": "2025-01-01T12:00:00",
        }
    ]
    text = format_history(history)
    assert "Test Question" in text
    assert "100%" in text


# --- format_preferences ---


def test_format_preferences():
    prefs = {
        "roles": ["backend_engineer"],
        "languages": ["Python"],
        "frameworks": ["Django"],
        "preferred_formats": ["mcq", "debugging"],
        "question_length": "standard",
    }
    text = format_preferences(prefs)
    assert "Backend Engineer" in text
    assert "Python" in text
    assert "Django" in text


def test_format_preferences_uses_whatsapp_bold():
    """Preferences should use *bold* not HTML."""
    prefs = {
        "roles": ["backend_engineer"],
        "languages": ["Python"],
        "frameworks": [],
        "preferred_formats": None,
        "question_length": "standard",
    }
    text = format_preferences(prefs)
    assert "<b>" not in text
    assert "*Your Preferences*" in text


# --- format_assessment_results ---


def test_format_assessment_results():
    results = {
        "programming_fundamentals": {
            "level": 3,
            "confidence": 0.65,
            "distribution": "L1: 5% L2: 15% L3: 65% L4: 10% L5: 5%",
        }
    }
    text = format_assessment_results(results)
    assert "Level Assessment Complete" in text
    assert "65%" in text


# --- format_session_summary ---


def test_format_session_summary_empty():
    text = format_session_summary([])
    assert "No questions" in text


def test_format_session_summary_with_data():
    results = [
        {
            "question": {
                "title": "Q1",
                "competency_slug": "programming_fundamentals",
            },
            "score": 0.8,
            "time_seconds": 30.0,
        },
        {
            "question": {
                "title": "Q2",
                "competency_slug": "data_structures_and_algorithms",
            },
            "score": 0.6,
            "time_seconds": 45.0,
        },
    ]
    text = format_session_summary(results)
    assert "Session Summary" in text
    assert "70%" in text  # average of 80% and 60%


# --- format_bookmarks ---


def test_format_bookmarks_empty():
    assert "No bookmarks" in format_bookmarks([])


# --- format_competencies ---


def test_format_competencies():
    text = format_competencies({}, ["programming_fundamentals"])
    assert "Competency Areas" in text
    assert "Programming Fundamentals" in text


def test_format_competencies_uses_whatsapp_bold():
    """Competencies should use *bold* not HTML."""
    text = format_competencies({}, ["programming_fundamentals"])
    assert "<b>" not in text
    assert "*Competency Areas*" in text


# --- WhatsApp markdown (no HTML) ---


def test_no_html_in_question():
    """WhatsApp formatter should not produce HTML tags."""
    question = {
        "competency_slug": "programming_fundamentals",
        "difficulty": 3,
        "format": "short_answer",
        "title": "Test <script>alert('xss')</script>",
        "body": "What is x < y && y > z?",
        "code_snippet": None,
        "language": None,
        "options": None,
        "correct_answer": None,
        "metadata": None,
    }
    parts = format_question(question)
    text = parts[0]
    # WhatsApp uses plain text markdown, not HTML — no escaping needed,
    # but <pre>, <b>, <code> tags should never appear
    assert "<pre>" not in text
    assert "<b>" not in text
    assert "<code>" not in text


def test_code_uses_backtick_blocks():
    """Code snippets should use triple backtick blocks, not HTML <pre>/<code>."""
    question = {
        "competency_slug": "programming_fundamentals",
        "difficulty": 2,
        "format": "debugging",
        "title": "Find Bug",
        "body": "What is wrong?",
        "code_snippet": "print('hello')",
        "language": "python",
        "options": None,
        "correct_answer": None,
        "metadata": None,
    }
    parts = format_question(question)
    text = "\n".join(parts)
    assert "```" in text
    assert "<pre>" not in text
    assert "<code>" not in text
