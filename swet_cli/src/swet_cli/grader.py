"""Answer grading: auto-grades MCQ, calls Claude for open-ended formats."""

import json
import logging

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from swet_cli.config import get_config
from swet_cli.llm import chat
from swet_cli.models import CriterionScore, GradeResult
from swet_cli.prompts import build_grading_prompt

logger = logging.getLogger(__name__)


def grade_mcq(selected_option: str, correct_answer: str) -> GradeResult:
    """Instantly grade an MCQ answer by comparing with correct answer."""
    is_correct = selected_option.upper() == correct_answer.upper()
    return GradeResult(
        criteria_scores=[
            CriterionScore(
                name="Correctness",
                score=1 if is_correct else 0,
                max_points=1,
                feedback="Correct!" if is_correct else f"Incorrect. The correct answer is {correct_answer}.",
            )
        ],
        total_score=1 if is_correct else 0,
        max_score=1,
        normalized_score=1.0 if is_correct else 0.0,
        overall_feedback="Well done!" if is_correct else "Better luck next time.",
    )


def _parse_grade_response(raw_text: str) -> GradeResult:
    """Parse and validate the LLM's grading JSON response."""
    text = raw_text.strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[:-3].rstrip()

    data = json.loads(text)
    return GradeResult.model_validate(data)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((anthropic.APIConnectionError, anthropic.APITimeoutError)),
)
def grade_open_ended(
    question_title: str,
    question_body: str,
    question_format: str,
    rubric: dict,
    answer_text: str,
    code_snippet: str | None = None,
) -> GradeResult:
    """Grade an open-ended answer using Claude.

    Args:
        question_title: The question title.
        question_body: The full question body.
        question_format: The question format.
        rubric: The grading rubric dict.
        answer_text: The candidate's answer.
        code_snippet: Optional code snippet for code-based questions.

    Returns:
        A validated GradeResult.
    """
    config = get_config()
    system_msg, user_msg = build_grading_prompt(
        question_title=question_title,
        question_body=question_body,
        question_format=question_format,
        rubric=rubric,
        answer_text=answer_text,
        code_snippet=code_snippet,
    )

    raw_text = chat(system=system_msg, user_message=user_msg, model=config.grading_model)
    return _parse_grade_response(raw_text)
