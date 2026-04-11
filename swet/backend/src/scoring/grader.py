"""AI grading via LLM (SPEC-031).

Handles sending answer text to the LLM for evaluation against
a grading rubric, parsing the structured score output, and retrying
on transient failures.
"""

import json
import logging

import anthropic
import openai
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.llm_client import chat_completion

logger = logging.getLogger(__name__)

GRADING_MODEL = settings.llm_grading_model
MAX_TOKENS = 4096

GRADING_SYSTEM_PROMPT = """\
You are an expert software engineering assessment grader. Your task is to \
evaluate a candidate's answer against a provided rubric with specific criteria.

IMPORTANT RULES:
1. Return ONLY a JSON object with the grading result. No markdown fences, no extra text.
2. Score each criterion independently based on the key indicators.
3. Be fair but rigorous. Partial credit is appropriate when some indicators are met.
4. Provide specific, constructive feedback referencing the candidate's actual answer.
5. The total score must equal the sum of individual criterion scores.
"""


class CriterionScore(BaseModel):
    """Score for a single rubric criterion."""

    name: str
    score: int = Field(ge=0)
    max_points: int
    feedback: str


class GradeResult(BaseModel):
    """Structured result from AI grading."""

    criteria_scores: list[CriterionScore]
    total_score: int = Field(ge=0)
    max_score: int
    normalized_score: float = Field(ge=0.0, le=1.0)
    overall_feedback: str


def _build_grading_prompt(
    question_title: str,
    question_body: str,
    question_format: str,
    rubric: dict[str, object],
    answer_text: str,
    code_snippet: str | None = None,
) -> str:
    """Build the user message for grading an answer."""
    prompt_parts = [
        f"QUESTION FORMAT: {question_format}",
        f"QUESTION TITLE: {question_title}",
        f"QUESTION BODY:\n{question_body}",
    ]

    if code_snippet:
        prompt_parts.append(f"CODE SNIPPET:\n{code_snippet}")

    prompt_parts.extend(
        [
            f"GRADING RUBRIC:\n{json.dumps(rubric, indent=2)}",
            f"CANDIDATE'S ANSWER:\n{answer_text}",
            "",
            "Grade the answer against each criterion in the rubric.",
            "Return a JSON object with this exact structure:",
            json.dumps(
                {
                    "criteria_scores": [
                        {
                            "name": "criterion name",
                            "score": 0,
                            "max_points": 0,
                            "feedback": "specific feedback",
                        }
                    ],
                    "total_score": 0,
                    "max_score": 0,
                    "normalized_score": 0.0,
                    "overall_feedback": "summary feedback",
                },
                indent=2,
            ),
            "",
            "Return ONLY the JSON object, nothing else.",
        ]
    )

    return "\n\n".join(prompt_parts)


def _log_retry(retry_state: object) -> None:
    """Log retry attempts for observability."""
    logger.warning("LLM grading API retry attempt %s", retry_state)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=5, min=5, max=300),
    retry=retry_if_exception_type(
        (
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
            openai.APIConnectionError,
            openai.APITimeoutError,
        )
    ),
    before_sleep=_log_retry,
)
async def _call_llm_for_grading(user_message: str) -> str:
    """Call LLM for grading with retry logic."""
    text, input_tokens, output_tokens = await chat_completion(
        model=GRADING_MODEL,
        system=GRADING_SYSTEM_PROMPT,
        user_message=user_message,
        max_tokens=MAX_TOKENS,
    )

    logger.info(
        "Grading API usage: input=%d, output=%d tokens",
        input_tokens,
        output_tokens,
    )

    return text


def _parse_grade_result(raw_text: str) -> GradeResult:
    """Parse LLM's grading output into a GradeResult."""
    text = raw_text.strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[:-3].rstrip()

    data = json.loads(text)
    return GradeResult.model_validate(data)


async def grade_answer(
    question_title: str,
    question_body: str,
    question_format: str,
    rubric: dict[str, object],
    answer_text: str,
    code_snippet: str | None = None,
) -> GradeResult:
    """Grade a single answer using the configured LLM.

    Args:
        question_title: The question title.
        question_body: The full question body.
        question_format: The question format (code_review, debugging, etc.).
        rubric: The grading rubric dict.
        answer_text: The candidate's response text.
        code_snippet: Optional code snippet for code-based questions.

    Returns:
        GradeResult with per-criterion scores and overall feedback.
    """
    prompt = _build_grading_prompt(
        question_title=question_title,
        question_body=question_body,
        question_format=question_format,
        rubric=rubric,
        answer_text=answer_text,
        code_snippet=code_snippet,
    )

    raw_text = await _call_llm_for_grading(prompt)
    return _parse_grade_result(raw_text)
