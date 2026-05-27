"""Unit tests for `alerts.telegram`.

Pure functions + httpx stub. No real network, no real channel.
"""

from __future__ import annotations

import httpx
import pytest

from job_crawler.alerts.telegram import (
    _format_salary,
    _summarise_description,
    format_new_job,
    send_message,
)

# ---------------------------------------------------------------------------
# format_new_job — content + escaping
# ---------------------------------------------------------------------------


def test_format_new_job_minimal_fields() -> None:
    """Title + URL only — the bare minimum a new posting carries."""
    body = format_new_job(
        title="Senior Python Engineer",
        company_name=None, city_name=None, country_code=None,
        category_code=None, category_name=None,
        url="https://example.invalid/job/1",
    )
    assert "🆕" in body
    assert "Senior Python Engineer" in body
    assert "example.invalid/job/1" in body
    assert "🔗" in body  # canonical-link footer


def test_format_new_job_full_fields() -> None:
    body = format_new_job(
        title="Senior Python Engineer",
        company_name="Tamara",
        city_name="Riyadh",
        country_code="sa",
        category_code="software_engineering",
        category_name="Software Engineering",
        description=(
            "About the role\n"
            "We are looking for a senior backend engineer.\n"
            "You will work on our payments platform.\n"
            "Requirements: Python, PostgreSQL, AWS.\n"
            "Saudi-based; relocation supported."
        ),
        salary_min=15000, salary_max=25000,
        salary_currency="SAR", salary_period="monthly",
        url="https://job-boards.eu.greenhouse.io/tamara/jobs/4683204101",
    )
    assert "🏢 Tamara" in body
    assert "💼 Software Engineering" in body
    assert "📍 Riyadh, SA" in body
    assert "SAR 15,000-25,000 / monthly" in body
    assert "payments platform" in body  # summary
    assert "#tamara" in body
    assert "#software_engineering" in body
    assert "#riyadh" in body


def test_format_new_job_escapes_html() -> None:
    """A company name containing &/</> must not break the HTML
    parse_mode body."""
    body = format_new_job(
        title="QA & Test Engineer",
        company_name="<script>alert(1)</script>",
        city_name="Riyadh", country_code="sa",
        category_code=None, category_name=None,
        url="https://example.invalid/job/x",
    )
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "&amp;" in body  # the & in the title


# ---------------------------------------------------------------------------
# _summarise_description — 3-5 line summary
# ---------------------------------------------------------------------------


def test_summarise_keeps_first_3_to_5_lines() -> None:
    desc = (
        "Line 1: about\n"
        "Line 2: the role\n"
        "Line 3: details\n"
        "Line 4: more details\n"
        "Line 5: even more\n"
        "Line 6: should be dropped\n"
        "Line 7: also dropped\n"
    )
    out = _summarise_description(desc)
    assert out is not None
    assert "Line 1" in out
    assert "Line 5" in out
    assert "Line 6" not in out
    assert "Line 7" not in out


def test_summarise_falls_back_to_sentences_when_one_paragraph() -> None:
    """A common JSON-LD shape: one long paragraph with sentence-end
    punctuation."""
    desc = (
        "We are hiring a senior backend engineer. "
        "You will own the payments platform. "
        "Stack: Python, PostgreSQL, AWS. "
        "Saudi-based; relocation supported. "
        "Apply via the link below."
    )
    out = _summarise_description(desc)
    assert out is not None
    # Should split into ~5 sentences
    assert "senior backend engineer" in out
    assert "Saudi-based" in out
    # Cap should not blow the budget
    assert len(out) <= 600 + 1


def test_summarise_empty_returns_none() -> None:
    assert _summarise_description(None) is None
    assert _summarise_description("") is None
    assert _summarise_description("   \n  \n ") is None


def test_summarise_caps_total_chars() -> None:
    desc = "x" * 5000
    out = _summarise_description(desc)
    assert out is not None
    assert len(out) <= 600 + 1


# ---------------------------------------------------------------------------
# _format_salary
# ---------------------------------------------------------------------------


def test_format_salary_range() -> None:
    assert _format_salary(10000, 15000, "SAR", "monthly") == "SAR 10,000-15,000 / monthly"


def test_format_salary_single_value() -> None:
    assert _format_salary(12000, None, "SAR", "monthly") == "SAR 12,000 / monthly"
    assert _format_salary(None, 12000, "SAR", "monthly") == "SAR 12,000 / monthly"


def test_format_salary_none_when_both_missing() -> None:
    assert _format_salary(None, None, "SAR", "monthly") is None


def test_format_salary_default_currency_period() -> None:
    """When the source didn't surface them, fall back to SAR/monthly
    (the SA-board convention)."""
    assert _format_salary(10000, None, None, None) == "SAR 10,000 / monthly"


# ---------------------------------------------------------------------------
# send_message — env handling + httpx transport stub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_skips_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No TELEGRAM_BOT_TOKEN env → silent no-op, returns False."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
    assert await send_message("hello") is False


@pytest.mark.asyncio
async def test_send_message_swallows_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection error from httpx must not propagate — alerter must
    never crash the calling crawler."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test")
    monkeypatch.setenv("TELEGRAM_RATE_LIMIT_MS", "0")

    # Force httpx.AsyncClient.post to raise via monkeypatching the class.
    async def _boom(self: httpx.AsyncClient, *args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("simulated network failure")

    monkeypatch.setattr(httpx.AsyncClient, "post", _boom)
    result = await send_message("hello")
    assert result is False


@pytest.mark.asyncio
async def test_send_message_returns_true_on_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path — a 200 from Telegram returns True."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test")
    monkeypatch.setenv("TELEGRAM_RATE_LIMIT_MS", "0")
    captured: dict[str, object] = {}

    async def _ok(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx.AsyncClient, "post", _ok)
    assert await send_message("hello world") is True
    assert "api.telegram.org/botx:y/sendMessage" in str(captured["url"])
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["chat_id"] == "@test"
    assert payload["text"] == "hello world"
    assert payload["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_send_message_returns_false_on_4xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test")
    monkeypatch.setenv("TELEGRAM_RATE_LIMIT_MS", "0")

    async def _bad(self: httpx.AsyncClient, *args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    monkeypatch.setattr(httpx.AsyncClient, "post", _bad)
    assert await send_message("hello") is False
