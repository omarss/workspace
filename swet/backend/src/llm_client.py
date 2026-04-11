"""Unified LLM client that supports both Anthropic and OpenAI-compatible endpoints.

When `settings.llm_base_url` is set, routes requests through an OpenAI-compatible
proxy (e.g. a local gateway at http://127.0.0.1:3456/v1). Otherwise, calls
the Anthropic API directly.
"""

import logging

import anthropic
import openai

from src.config import settings

logger = logging.getLogger(__name__)


def use_openai_compat() -> bool:
    """Check if we should use the OpenAI-compatible endpoint."""
    return bool(settings.llm_base_url)


def create_anthropic_client() -> anthropic.AsyncAnthropic:
    """Create an Anthropic async client for direct API usage."""
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


def create_openai_client() -> openai.AsyncOpenAI:
    """Create an OpenAI async client pointed at the configured base URL."""
    return openai.AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=300.0,  # 5 min timeout for large generation requests
    )


async def chat_completion(
    *,
    model: str,
    system: str,
    user_message: str,
    max_tokens: int,
) -> tuple[str, int, int]:
    """Send a chat completion request to the configured LLM backend.

    Returns:
        Tuple of (response_text, input_tokens, output_tokens).

    Raises:
        ValueError: If the response contains no text content.
        anthropic.APIConnectionError: On transient Anthropic errors.
        openai.APIConnectionError: On transient OpenAI errors.
    """
    if use_openai_compat():
        return await _openai_chat(
            model=model,
            system=system,
            user_message=user_message,
            max_tokens=max_tokens,
        )
    return await _anthropic_chat(
        model=model,
        system=system,
        user_message=user_message,
        max_tokens=max_tokens,
    )


async def _anthropic_chat(
    *,
    model: str,
    system: str,
    user_message: str,
    max_tokens: int,
) -> tuple[str, int, int]:
    """Call Anthropic Messages API directly."""
    client = create_anthropic_client()
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        raise ValueError("LLM returned no text content")

    return (
        text_blocks[0],
        response.usage.input_tokens,
        response.usage.output_tokens,
    )


async def _openai_chat(
    *,
    model: str,
    system: str,
    user_message: str,
    max_tokens: int,
) -> tuple[str, int, int]:
    """Call an OpenAI-compatible chat completions endpoint."""
    client = create_openai_client()
    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    )

    choice = response.choices[0] if response.choices else None
    if not choice or not choice.message.content:
        raise ValueError("LLM returned no text content")

    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0

    return (choice.message.content, input_tokens, output_tokens)
