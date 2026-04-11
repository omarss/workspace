"""LLM client supporting both Anthropic API and OpenAI-compatible proxies.

When SWET_CLI_BASE_URL is set, routes through an OpenAI-compatible endpoint
(e.g. claude-max-api at http://localhost:3456/v1). Otherwise calls Anthropic directly.
"""

import logging

import anthropic

from swet_cli.config import get_config

logger = logging.getLogger(__name__)

MAX_TOKENS = 4096


def chat(system: str, user_message: str, model: str | None = None) -> str:
    """Send a message to an LLM and return the text response.

    Automatically routes to Anthropic or an OpenAI-compatible proxy
    based on config.llm_base_url.

    Args:
        system: System prompt.
        user_message: User message.
        model: Model ID override. Defaults to the generation model from config.

    Returns:
        The text response from the LLM.

    Raises:
        ValueError: If the response contains no text content.
    """
    config = get_config()
    model = model or config.generation_model

    if config.llm_base_url:
        return _openai_chat(system, user_message, model)
    return _anthropic_chat(system, user_message, model)


def _anthropic_chat(system: str, user_message: str, model: str) -> str:
    """Call Anthropic Messages API directly."""
    config = get_config()
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        raise ValueError("LLM returned no text content")

    logger.info(
        "LLM usage: model=%s input=%d output=%d tokens",
        model,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    return text_blocks[0]


def _openai_chat(system: str, user_message: str, model: str) -> str:
    """Call an OpenAI-compatible endpoint (e.g. claude-max-api proxy)."""
    # Import here to keep openai as an optional dependency
    try:
        import openai
    except ImportError:
        raise ImportError(
            "The 'openai' package is required when using SWET_CLI_BASE_URL. Install it with: pip install openai"
        ) from None

    config = get_config()
    client = openai.OpenAI(
        base_url=config.llm_base_url,
        api_key=config.anthropic_api_key,  # proxy doesn't validate this
        timeout=300.0,
    )

    response = client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
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
    logger.info(
        "LLM usage (proxy): model=%s input=%d output=%d tokens",
        model,
        input_tokens,
        output_tokens,
    )

    return choice.message.content
