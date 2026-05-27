"""Telegram alerts — broadcast newly-ingested jobs to a channel.

Mirrors `alerts/email.py`'s philosophy: no paid-SaaS dep, env-driven,
never crashes the caller on a transport failure. Channel posts use
the official Telegram Bot API (`api.telegram.org/bot<TOKEN>/sendMessage`)
via `httpx` (already in the dep tree).

Environment variables (all required for a message to actually be sent;
otherwise this module logs INFO and exits cleanly):

    TELEGRAM_BOT_TOKEN       e.g. 12345:AAH...
    TELEGRAM_CHANNEL_ID      e.g. @sa_jobs_feed   (public handle)
                                  -1003978090152  (numeric for private)
    TELEGRAM_RATE_LIMIT_MS   optional, default 350 — minimum gap between
                             two consecutive sends so a runaway run can't
                             hit Telegram's 30-msg/s channel throttle.

Module-level state (`_LAST_SEND_TS`) enforces the rate limit per
process. Cross-process coordination isn't needed because the cron
runs only one container at a time (concurrencyPolicy=Forbid in the
k3s CronJob).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from decimal import Decimal
from typing import Final

import httpx

# Salary fields come through as Decimal from the pydantic model, but the
# parsers occasionally pass plain int/float during construction. Accept
# all numeric shapes; reject None at the call site.
SalaryNum = Decimal | float | int

_LOG: Final = logging.getLogger("job_crawler.alerts.telegram")

# Telegram caps channel sends at ~30/sec and per-chat at 1/sec. Stay
# well under both by spacing sends ~350ms apart (~3/sec). A single run
# producing 50 new jobs (the typical `--max-alerts` cap) finishes in
# ~17 seconds of background trickle.
_DEFAULT_RATE_LIMIT_MS: Final = 350
_LAST_SEND_TS: float = 0.0

# Telegram message body cap — anything longer is rejected. We
# truncate well below the limit because emoji + HTML escapes inflate.
_MAX_BODY_CHARS: Final = 3800


def _rate_limit_ms() -> int:
    """Read the rate-limit env with a sane fallback."""
    raw = os.environ.get("TELEGRAM_RATE_LIMIT_MS")
    if raw is None:
        return _DEFAULT_RATE_LIMIT_MS
    try:
        return max(0, int(raw))
    except ValueError:
        _LOG.warning(
            "TELEGRAM_RATE_LIMIT_MS=%r is not an integer; using default %dms",
            raw, _DEFAULT_RATE_LIMIT_MS,
        )
        return _DEFAULT_RATE_LIMIT_MS


async def send_message(
    text: str,
    *,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
) -> bool:
    """POST one message to the configured channel.

    Returns True on a 2xx response from Telegram. Never raises —
    the alerter must not break a crawl run on a Telegram outage,
    bad token, or transient network failure.

    Caller is responsible for formatting `text`. When `parse_mode=HTML`,
    HTML-special chars in dynamic parts must already be escaped by the
    caller (`html.escape`); see `format_new_job` for the canonical
    helper that does this.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    channel = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not channel:
        _LOG.info("TELEGRAM_BOT_TOKEN/CHANNEL_ID unset; skipping send")
        return False

    if len(text) > _MAX_BODY_CHARS:
        text = text[:_MAX_BODY_CHARS - 1] + "…"

    # Per-process rate limit. `asyncio.sleep` instead of `time.sleep`
    # so concurrent senders share the budget cleanly.
    global _LAST_SEND_TS
    gap = _rate_limit_ms() / 1000.0
    now = time.monotonic()
    delta = now - _LAST_SEND_TS
    if delta < gap:
        await asyncio.sleep(gap - delta)
    _LAST_SEND_TS = time.monotonic()

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": channel,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        _LOG.warning("telegram send failed (transport): %s", exc)
        return False
    if resp.status_code >= 400:
        _LOG.warning(
            "telegram send failed (status=%d): %s",
            resp.status_code, resp.text[:300],
        )
        return False
    return True


def _format_salary(
    salary_min: SalaryNum | None,
    salary_max: SalaryNum | None,
    salary_currency: str | None,
    salary_period: str | None,
) -> str | None:
    """Render a human-readable salary line, or None when nothing useful."""
    if salary_min is None and salary_max is None:
        return None
    cur = (salary_currency or "SAR").upper()
    period = (salary_period or "monthly").lower()
    if salary_min is not None and salary_max is not None and salary_min != salary_max:
        # ASCII hyphen for the range separator — keeps the source lint-clean.
        return f"{cur} {int(salary_min):,}-{int(salary_max):,} / {period}"
    val: SalaryNum = salary_min if salary_min is not None else salary_max  # type: ignore[assignment]
    return f"{cur} {int(val):,} / {period}"


def _slug(value: str | None) -> str | None:
    """Lower + replace non-word with underscore — for hashtags."""
    if not value:
        return None
    import re
    out = re.sub(r"\W+", "_", value.strip().lower()).strip("_")
    return out or None


# Description summary — first N non-empty lines, capped at M chars.
# Telegram's 4096-byte limit isn't the constraint; readability is.
# A tight 3-5 line summary keeps the channel scannable.
_SUMMARY_MAX_LINES: Final = 5
_SUMMARY_MIN_LINES: Final = 3
_SUMMARY_MAX_CHARS: Final = 600


def _summarise_description(description: str | None) -> str | None:
    """Return the first 3-5 non-empty lines (~600 chars cap) of the
    description. Designed to give the reader a quick "what's the role"
    glance without burying the canonical link.

    Falls back gracefully on:
      * None / empty → None (skip the line)
      * Single-paragraph blob → first ~3-4 sentences
      * Excess length → truncate with ellipsis at the boundary
    """
    if not description:
        return None
    # Defensive char stripping — the runner's `_clean_text` already
    # ran in to_upsert, but a posting that bypassed the chokepoint
    # (e.g. cluster description backfilled via a different path)
    # could still carry invisibles or control chars. Re-apply here.
    from ..core.normalise import _clean_text
    cleaned = _clean_text(description)
    if not cleaned:
        return None
    import re
    text = cleaned.strip()
    if not text:
        return None

    # Try line-based split first; only fall back to sentence-split when
    # the description is one giant unbroken paragraph (common on
    # JSON-LD descriptions from Greenhouse / Workday).
    raw_lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in raw_lines if line]
    if len(lines) < _SUMMARY_MIN_LINES:
        # Sentence-fallback: split on . / ! / ? / Arabic full-stop ؟
        sentences = [s.strip() for s in re.split(r"(?<=[.!?؟])\s+", text) if s.strip()]
        lines = sentences[:_SUMMARY_MAX_LINES] if sentences else lines

    picked: list[str] = []
    running = 0
    for line in lines[:_SUMMARY_MAX_LINES]:
        # Cap per-line at ~150 chars so a single huge line doesn't
        # eat the whole budget.
        if len(line) > 200:
            line = line[:197] + "…"
        if running + len(line) > _SUMMARY_MAX_CHARS and picked:
            break
        picked.append(line)
        running += len(line) + 1  # +1 for the newline join
        if running >= _SUMMARY_MAX_CHARS:
            break
    if not picked:
        return None
    summary = "\n".join(picked)
    # Final hard cap
    if len(summary) > _SUMMARY_MAX_CHARS:
        summary = summary[: _SUMMARY_MAX_CHARS - 1] + "…"
    return summary


def format_new_job(
    *,
    title: str,
    company_name: str | None,
    city_name: str | None,
    country_code: str | None,
    category_code: str | None,
    category_name: str | None,
    description: str | None = None,
    salary_min: SalaryNum | None = None,
    salary_max: SalaryNum | None = None,
    salary_currency: str | None = None,
    salary_period: str | None = None,
    url: str,
) -> str:
    """Build the HTML-formatted message body for one newly-ingested job.

    Caller is responsible for passing CLEAN already-stripped values —
    the runner already does this via `_clean_title` / `_clean_company_name`
    before calling us. `url` is the authoritative source URL (the
    `canonical_url` of the canonical posting in the cluster).
    """
    import html

    lines: list[str] = []
    safe_title = html.escape(title or "—")
    safe_url = html.escape(url or "", quote=True)
    lines.append(f"🆕 <b><a href=\"{safe_url}\">{safe_title}</a></b>")

    if company_name or category_name:
        parts = []
        if company_name:
            parts.append(f"🏢 {html.escape(company_name)}")
        if category_name:
            parts.append(f"💼 {html.escape(category_name)}")
        lines.append(" · ".join(parts))

    if city_name or country_code:
        loc = ", ".join(p for p in (city_name, (country_code or "").upper()) if p)
        if loc:
            lines.append(f"📍 {html.escape(loc)}")

    salary = _format_salary(salary_min, salary_max, salary_currency, salary_period)
    if salary:
        lines.append(f"💰 {html.escape(salary)}")

    summary = _summarise_description(description)
    if summary:
        # Blank line to visually separate the header from the body.
        lines.append("")
        lines.append(html.escape(summary))

    # Canonical link footer — repeat the URL in plain form so users
    # can see (and copy) the actual source URL, not just the
    # hyperlinked title.
    if url:
        lines.append("")
        lines.append(f"🔗 {safe_url}")

    # Hashtags for filtering. Limited to ones that are universally
    # safe (company slug can contain spaces / Arabic, so we slugify).
    tags: list[str] = []
    for raw in (company_name, category_code, city_name, country_code):
        s = _slug(raw)
        if s:
            tags.append(f"#{s}")
    if tags:
        lines.append(" ".join(tags))

    return "\n".join(lines)
