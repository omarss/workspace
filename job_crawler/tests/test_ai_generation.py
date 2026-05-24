"""Pure-Python unit tests for the AI-generation heuristic.

These don't touch the database; they're here so failures show up in the
same `pytest` invocation as the integration suite.
"""

from __future__ import annotations

from job_crawler_db import AIDetectionResult, detect_ai_generation


def test_empty_input_returns_zero() -> None:
    result = detect_ai_generation("")
    assert isinstance(result, AIDetectionResult)
    assert result.score == 0.0
    assert result.confidence == 0.0
    assert result.hits == []


def test_none_input_returns_zero() -> None:
    result = detect_ai_generation(None)
    assert result.score == 0.0
    assert result.confidence == 0.0


def test_human_short_description_low_score() -> None:
    human = (
        "Looking for a backend engineer with 3+ years of Python experience. "
        "Must be comfortable with FastAPI and PostgreSQL. Salary 18-25k SAR. "
        "Send CV to careers@acme.sa."
    )
    result = detect_ai_generation(human)
    assert result.score < 0.20, f"expected low score for human text, got {result}"
    assert "llm_phrases" not in result.hits


def test_llm_loaded_long_description_high_score() -> None:
    # Synthetic — many LLM tells.
    text = " ".join(
        [
            "We are seeking a passionate Senior Software Engineer to join our team "
            "and embark on a journey of leveraging cutting-edge innovative solutions.",
            "In the dynamic landscape of today's fast-paced environment — our team "
            "harnesses the power of robust and scalable architectures — to make a "
            "meaningful impact across the organisation.",
            "You will be responsible for designing, building, and scaling cloud-native "
            "services. You will collaborate cross-functionally across product, design, "
            "and engineering. You will delve into complex problems and deliver world-class "
            "solutions in a fast-paced environment.",
            "We value innovative, collaborative, dynamic teammates who thrive on synergy "
            "and continuous learning in an ever-evolving industry.",
            "Strong communication skills, attention to detail, and the ability to drive "
            "impactful outcomes are essential. Cloud experience is a plus.",
            "We are an equal opportunity employer and all qualified applicants will "
            "receive consideration without regard to race, gender, or background.",
        ]
        * 2
    )
    result = detect_ai_generation(text)
    assert result.score >= 0.55, f"expected high score for LLM text, got {result}"
    assert "llm_phrases" in result.hits
    assert result.is_likely_ai() is True


def test_em_dash_density_signal_triggers() -> None:
    text = "Short — sentence — with — many — em — dashes — in — short — text." * 2
    result = detect_ai_generation(text)
    assert "em_dash_density" in result.hits


def test_triple_adjective_tic_detected() -> None:
    text = (
        "We're looking for someone innovative, collaborative, and dynamic to join us. "
        "You'll be building, shipping, and scaling things that matter."
    )
    result = detect_ai_generation(text)
    assert "triple_adjective_tic" in result.hits


def test_boilerplate_phrase_flagged() -> None:
    text = (
        "Senior Engineer for our Riyadh office. We are an equal opportunity employer "
        "and welcome candidates of all backgrounds."
    )
    result = detect_ai_generation(text)
    assert "boilerplate" in result.hits


def test_score_is_capped_in_unit_range() -> None:
    text = (
        "we are seeking a passionate engineer — embark on a journey — "
        "leverage your skills — in the dynamic landscape of cutting-edge — "
        "harness the power of fast-paced robust and scalable systems — "
        "collaborate cross-functionally — drive impactful outcomes — "
        "innovative, collaborative, dynamic — synergy — ever-evolving — "
        "we are an equal opportunity employer — "
    ) * 5
    result = detect_ai_generation(text)
    assert 0.0 <= result.score <= 1.0
    assert 0.0 <= result.confidence <= 1.0
