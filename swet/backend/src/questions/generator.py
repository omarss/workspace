"""Question generation via LLM API (SPEC-012).

Handles calling the LLM, parsing structured JSON output,
validating against format schemas, and retrying on transient failures.
"""

import json
import logging

import anthropic
import openai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.llm_client import chat_completion
from src.questions.prompts import build_generation_prompt
from src.questions.schemas import GeneratedQuestion

logger = logging.getLogger(__name__)

GENERATION_MODEL = settings.llm_generation_model
MAX_TOKENS = 16384


def _log_retry(retry_state: object) -> None:
    """Log retry attempts for observability."""
    logger.warning("LLM API retry attempt %s", retry_state)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=8),
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
async def _call_llm(system: str, user_message: str) -> str:
    """Call LLM API with retry logic for transient errors."""
    text, input_tokens, output_tokens = await chat_completion(
        model=GENERATION_MODEL,
        system=system,
        user_message=user_message,
        max_tokens=MAX_TOKENS,
    )

    logger.info(
        "LLM generation usage: input=%d, output=%d tokens",
        input_tokens,
        output_tokens,
    )

    return text


def _parse_and_validate(raw_text: str, expected_format: str) -> list[GeneratedQuestion]:
    """Parse LLM's JSON output and validate each question.

    Strips markdown fences if the LLM wraps the output despite instructions.
    Validates each question against the GeneratedQuestion schema.
    """
    text = raw_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove opening fence (possibly with language hint like ```json)
        first_newline = text.index("\n")
        text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[:-3].rstrip()

    data = json.loads(text)

    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array, got {type(data).__name__}")

    validated: list[GeneratedQuestion] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("Question %d is not a dict, skipping", i)
            continue

        # Inject the expected format if missing (some prompts may not echo it back)
        if "format" not in item:
            item["format"] = expected_format

        try:
            question = GeneratedQuestion.model_validate(item)
            validated.append(question)
        except Exception as e:
            logger.warning("Question %d failed validation: %s", i, e)
            continue

    return validated


async def generate_questions(
    competency_name: str,
    competency_description: str,
    difficulty: int,
    question_format: str,
    role: str,
    languages: list[str],
    frameworks: list[str],
    count: int = 20,
) -> list[GeneratedQuestion]:
    """Generate questions via LLM API.

    This is the main entry point for question generation. It builds the prompt,
    calls the LLM, parses the response, and validates each question.

    Args:
        competency_name: Human-readable competency name.
        competency_description: Competency description for context.
        difficulty: Difficulty level 1-5.
        question_format: One of the 5 supported formats.
        role: User's primary engineering role.
        languages: User's programming languages.
        frameworks: User's frameworks.
        count: Number of questions to generate (default 20).

    Returns:
        List of validated GeneratedQuestion objects.

    Raises:
        ValueError: If LLM returns completely unparseable output after retries.
    """
    system, user_message = build_generation_prompt(
        competency_name=competency_name,
        competency_description=competency_description,
        difficulty=difficulty,
        question_format=question_format,
        role=role,
        languages=languages,
        frameworks=frameworks,
        count=count,
    )

    raw_text = await _call_llm(system, user_message)
    questions = _parse_and_validate(raw_text, expected_format=question_format)

    if not questions:
        raise ValueError(
            f"LLM returned no valid questions for {question_format} "
            f"(competency={competency_name}, difficulty={difficulty})"
        )

    logger.info(
        "Generated %d/%d valid questions for %s (competency=%s, difficulty=%d)",
        len(questions),
        count,
        question_format,
        competency_name,
        difficulty,
    )

    return questions
