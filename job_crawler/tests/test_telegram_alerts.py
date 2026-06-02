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
    body, buttons = format_new_job(
        title="Senior Python Engineer",
        company_name=None, city_name=None, country_code=None,
        category_code=None, category_name=None,
        url="https://example.invalid/job/1",
    )
    assert "🆕" in body
    assert "Senior Python Engineer" in body
    # Title is the clickable link (a href="..."), the plain 🔗 footer
    # was dropped in v3 — the inline View Job button replaces it.
    assert 'href="https://example.invalid/job/1"' in body
    assert "🔗" not in body
    assert buttons == [("👀 View full job", "https://example.invalid/job/1")]


def test_format_new_job_full_fields() -> None:
    from datetime import UTC, datetime
    # Fixed date so the test is stable. Format spec: "Wed, 21 May 2026".
    posted = datetime(2026, 5, 21, 9, 30, tzinfo=UTC)
    body, buttons = format_new_job(
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
        posted_at=posted,
        url="https://job-boards.eu.greenhouse.io/tamara/jobs/4683204101",
    )
    assert "🏢 Tamara" in body
    assert "💼 Software Engineering" in body
    assert "📍 Riyadh, SA" in body
    # Absolute date — meaningful even if user scrolls back weeks later.
    assert "📅 Posted Thu, 21 May 2026" in body
    assert "SAR 15,000-25,000 / monthly" in body
    assert "payments platform" in body  # summary
    assert "#tamara" in body
    assert "#software_engineering" in body
    assert "#riyadh" in body
    assert buttons[0][0].startswith("👀")
    assert buttons[0][1] == "https://job-boards.eu.greenhouse.io/tamara/jobs/4683204101"


def test_format_new_job_escapes_html() -> None:
    """A company name containing &/</> must not break the HTML
    parse_mode body."""
    body, _buttons = format_new_job(
        title="QA & Test Engineer",
        company_name="<script>alert(1)</script>",
        city_name="Riyadh", country_code="sa",
        category_code=None, category_name=None,
        url="https://example.invalid/job/x",
    )
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "&amp;" in body  # the & in the title


def test_format_new_job_skips_about_us_intro() -> None:
    """A description that opens with "About Us / About the company"
    boilerplate should have that paragraph stripped — subscribers
    don't care about the marketing pitch, they want the role."""
    body, _buttons = format_new_job(
        title="Application Support Engineer",
        company_name="Tamara",
        city_name="Riyadh", country_code="sa",
        category_code=None, category_name=None,
        description=(
            "About Us\n"
            "Tamara is the leading fintech platform in Saudi Arabia "
            "with millions of customers and partnerships with Apple, "
            "SHEIN, and noon.\n\n"
            "Your Role\n"
            "We are seeking a dedicated Application Support Engineer "
            "to investigate, troubleshoot, and resolve technical issues."
        ),
        url="https://example.invalid/job/1",
    )
    assert "Tamara is the leading fintech" not in body
    assert "Application Support Engineer" in body  # title
    assert "investigate, troubleshoot" in body


def test_format_new_job_skips_pitch_first_sentence() -> None:
    """Even without an explicit 'About Us' heading, a pitch sentence
    like 'Tamara is the leading ...' counts as boilerplate."""
    body, _ = format_new_job(
        title="Engineer",
        company_name="Tamara",
        city_name="Riyadh", country_code="sa",
        category_code=None, category_name=None,
        description=(
            "Tamara is the leading fintech platform in Saudi Arabia.\n\n"
            "You will own the payments platform and drive technical "
            "decisions across the stack."
        ),
        url="https://example.invalid/job/1",
    )
    assert "leading fintech platform" not in body
    assert "own the payments platform" in body


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
    """No TELEGRAM_BOT_TOKEN env → silent no-op, returns None."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
    assert await send_message("hello") is None


@pytest.mark.asyncio
async def test_send_message_swallows_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection error from httpx must not propagate — alerter must
    never crash the calling crawler. Failure is signalled by None."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test")
    monkeypatch.setenv("TELEGRAM_RATE_LIMIT_MS", "0")

    # Force httpx.AsyncClient.post to raise via monkeypatching the class.
    async def _boom(self: httpx.AsyncClient, *args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("simulated network failure")

    monkeypatch.setattr(httpx.AsyncClient, "post", _boom)
    result = await send_message("hello")
    assert result is None


@pytest.mark.asyncio
async def test_send_message_returns_message_id_on_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path — a 200 from Telegram returns the message_id from
    the JSON body's `result.message_id`. Inline_buttons pass through
    as reply_markup."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test")
    monkeypatch.setenv("TELEGRAM_RATE_LIMIT_MS", "0")
    captured: dict[str, object] = {}

    async def _ok(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 4242}})

    monkeypatch.setattr(httpx.AsyncClient, "post", _ok)
    result = await send_message(
        "hello world",
        inline_buttons=[("👀 View", "https://example.invalid/x")],
    )
    assert result == 4242
    assert "api.telegram.org/botx:y/sendMessage" in str(captured["url"])
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["chat_id"] == "@test"
    assert payload["text"] == "hello world"
    assert payload["parse_mode"] == "HTML"
    markup = payload["reply_markup"]
    assert isinstance(markup, dict)
    assert markup["inline_keyboard"] == [
        [{"text": "👀 View", "url": "https://example.invalid/x"}]
    ]


@pytest.mark.asyncio
async def test_send_message_falls_back_to_sentinel_on_missing_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2xx body without a `result.message_id` returns -1 (sentinel:
    sent but id unknown). Callers should treat any non-None return as
    'sent'; the sentinel separates 'sent without id' from 'sent with id'
    so the DB can store NULL rather than a fake id."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test")
    monkeypatch.setenv("TELEGRAM_RATE_LIMIT_MS", "0")

    async def _ok_no_id(self: httpx.AsyncClient, *a: object, **kw: object) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx.AsyncClient, "post", _ok_no_id)
    assert await send_message("hello") == -1


@pytest.mark.asyncio
async def test_send_message_returns_none_on_4xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test")
    monkeypatch.setenv("TELEGRAM_RATE_LIMIT_MS", "0")

    async def _bad(self: httpx.AsyncClient, *args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    monkeypatch.setattr(httpx.AsyncClient, "post", _bad)
    assert await send_message("hello") is None


# ---------------------------------------------------------------------------
# 429 backoff — respect `parameters.retry_after` and retry once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_retries_once_after_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First 429 → sleep `retry_after` seconds, then retry once. The
    retry succeeds → return the new message_id. Verifies we honour the
    server's pacing instead of giving up the first time the channel
    saturates."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test")
    monkeypatch.setenv("TELEGRAM_RATE_LIMIT_MS", "0")

    calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)

    call_count = {"n": 0}

    async def _flaky(self: httpx.AsyncClient, *a: object, **kw: object) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(
                429,
                json={
                    "ok": False,
                    "error_code": 429,
                    "description": "Too Many Requests: retry after 7",
                    "parameters": {"retry_after": 7},
                },
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 999}})

    monkeypatch.setattr(httpx.AsyncClient, "post", _flaky)
    result = await send_message("hello")
    assert result == 999
    assert call_count["n"] == 2
    # The retry slept for 7 + 1 buffer = 8 seconds
    assert 8 in [round(s) for s in calls]


@pytest.mark.asyncio
async def test_send_message_gives_up_on_second_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two consecutive 429s → return None. The channel is genuinely
    saturated; the next crawl cycle's broadcaster will retry from
    scratch (dedup ledger prevents double-post)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test")
    monkeypatch.setenv("TELEGRAM_RATE_LIMIT_MS", "0")

    async def _fake_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)

    async def _always_429(self: httpx.AsyncClient, *a: object, **kw: object) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry after 13",
                "parameters": {"retry_after": 13},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", _always_429)
    assert await send_message("hello") is None


@pytest.mark.asyncio
async def test_send_message_429_with_missing_retry_after_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the 429 body lacks `parameters.retry_after`, fall back to a
    30-second sleep — Telegram's documented minimum."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test")
    monkeypatch.setenv("TELEGRAM_RATE_LIMIT_MS", "0")

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)

    call_count = {"n": 0}

    async def _429_then_ok(
        self: httpx.AsyncClient, *a: object, **kw: object,
    ) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(429, json={"ok": False, "description": "TMR"})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr(httpx.AsyncClient, "post", _429_then_ok)
    assert await send_message("hello") == 1
    # Default 30s + 1s buffer
    assert any(s >= 30 for s in sleeps)


@pytest.mark.asyncio
async def test_send_message_clamps_huge_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An absurd `retry_after` value (Telegram occasionally returns
    >hour) is clamped to `_MAX_RETRY_AFTER_SECONDS` so the run can't
    hang for an hour on a single bad reply."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test")
    monkeypatch.setenv("TELEGRAM_RATE_LIMIT_MS", "0")

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)

    call_count = {"n": 0}

    async def _abuse(self: httpx.AsyncClient, *a: object, **kw: object) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(
                429,
                json={
                    "ok": False,
                    "description": "TMR",
                    "parameters": {"retry_after": 999999},
                },
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 2}})

    monkeypatch.setattr(httpx.AsyncClient, "post", _abuse)
    assert await send_message("hello") == 2
    # Clamped to 120s ceiling + 1s buffer
    assert max(sleeps) <= 121


# ---------------------------------------------------------------------------
# v3 polish — trim trailing anchors + sentence-boundary truncation
# ---------------------------------------------------------------------------


def test_summarise_trims_trailing_anchor_heading() -> None:
    """A summary that picks up a NEXT section's heading at the tail
    (e.g. ends with 'Your Impact' on its own line) should drop that
    dangling header. Live regression from the Cisco post screenshot."""
    desc = (
        "Meet the Team\n"
        "Our Account Executive team plays a critical role in supporting "
        "the Kingdom's digital transformation agenda.\n"
        "We partner with government entities, semi-governmental entities, "
        "and large enterprises.\n"
        "We are a high-performing, collaborative team.\n"
        "Your Impact"  # heading with no body — should be dropped
    )
    out = _summarise_description(desc)
    assert out is not None
    assert "Your Impact" not in out  # the trailing heading is gone
    assert "high-performing" in out  # actual body content preserved


def test_summarise_truncates_at_sentence_boundary_not_midword() -> None:
    """When the per-line cap fires, prefer cutting at a sentence end
    over splitting a word."""
    long_line = (
        "We are a global engineering team that builds payments. "
        "Our stack is Python, PostgreSQL, and AWS. "
        "We hire senior contributors who want to own systems end-to-end. "
        "You will work with partners across the Kingdom of Saudi Arabia "
        "and lead key initiatives that drive measurable business outcomes."
    )
    out = _summarise_description(long_line)
    assert out is not None
    # No mid-word truncation — last char before ellipsis (if any) is
    # punctuation or a full word.
    assert not out.endswith("Saud…")
    # Should end either at a real period (preferred) or after a full word
    assert out.endswith(".") or out.endswith("…")
    if out.endswith("…"):
        # the char immediately before "…" should be whitespace-trimmed
        # to a word boundary (not a mid-word letter break)
        # the cut should happen at a word end
        assert out[-3] != "e" or out[-4] == " " or out[-2] == " "


def test_humanise_posted_at_absolute_format() -> None:
    from datetime import UTC, datetime

    from job_crawler.alerts.telegram import _humanise_posted_at
    # Single-digit day formatted without leading zero.
    assert _humanise_posted_at(datetime(2026, 5, 5, 12, 0, tzinfo=UTC)) == "Tue, 5 May 2026"
    # Two-digit day rendered as-is.
    assert _humanise_posted_at(datetime(2026, 5, 21, 9, 30, tzinfo=UTC)) == "Thu, 21 May 2026"
    # tz-naive coerced to UTC, still renders.
    assert _humanise_posted_at(datetime(2026, 12, 1, 0, 0)) == "Tue, 1 Dec 2026"
    # Missing / wrong type → None
    assert _humanise_posted_at(None) is None
    assert _humanise_posted_at("2026-05-27") is None


def test_format_new_job_renders_first_seen_when_posted_at_missing() -> None:
    """company_careers postings have no board-supplied posted_at —
    the runner passes first_seen_at as a fallback so subscribers
    still get a date anchor. Label switches from 'Posted' to
    'First seen' to make the provenance explicit."""
    from datetime import UTC, datetime
    first_seen = datetime(2026, 5, 27, 18, 30, tzinfo=UTC)
    body, _buttons = format_new_job(
        title="Senior Product Manager",
        company_name="Tamara", city_name="Riyadh", country_code="sa",
        category_code=None, category_name=None,
        description=("Role overview. " * 30),
        posted_at=None,
        first_seen_at=first_seen,
        url="https://example.invalid/careers/42",
    )
    assert "📅 First seen Wed, 27 May 2026" in body
    assert "📅 Posted" not in body


def test_format_new_job_prefers_posted_at_over_first_seen() -> None:
    """When both dates are supplied, the canonical posted_at wins."""
    from datetime import UTC, datetime
    body, _buttons = format_new_job(
        title="Senior Python Engineer",
        company_name="Tamara", city_name="Riyadh", country_code="sa",
        category_code=None, category_name=None,
        description=("Role overview. " * 30),
        posted_at=datetime(2026, 5, 21, 9, 30, tzinfo=UTC),
        first_seen_at=datetime(2026, 5, 27, 18, 30, tzinfo=UTC),
        url="https://example.invalid/careers/42",
    )
    assert "📅 Posted Thu, 21 May 2026" in body
    assert "First seen" not in body


def test_format_new_job_omits_date_line_when_both_missing() -> None:
    """Defensive: if both dates are None, no 📅 line is rendered.
    Runner is supposed to gate this out, but format_new_job should
    not crash."""
    body, _buttons = format_new_job(
        title="Senior Python Engineer",
        company_name=None, city_name=None, country_code=None,
        category_code=None, category_name=None,
        posted_at=None,
        first_seen_at=None,
        url="https://example.invalid/careers/42",
    )
    assert "📅" not in body
