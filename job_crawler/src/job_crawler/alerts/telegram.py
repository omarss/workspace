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
import re
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
    inline_buttons: list[tuple[str, str]] | None = None,
) -> bool:
    """POST one message to the configured channel.

    Returns True on a 2xx response from Telegram. Never raises —
    the alerter must not break a crawl run on a Telegram outage,
    bad token, or transient network failure.

    Caller is responsible for formatting `text`. When `parse_mode=HTML`,
    HTML-special chars in dynamic parts must already be escaped by the
    caller (`html.escape`); see `format_new_job` for the canonical
    helper that does this.

    `inline_buttons` is an optional list of (label, url) pairs rendered
    as a horizontal row of tap-targets below the message body — Telegram
    natively renders these as proper buttons on mobile + desktop. Each
    button opens the URL when tapped.
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
    payload: dict[str, object] = {
        "chat_id": channel,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if inline_buttons:
        # One row, N buttons. Telegram's inline_keyboard is a list of
        # rows; each row is a list of {text, url} dicts.
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": label, "url": btn_url} for label, btn_url in inline_buttons]
            ]
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


# Anchor headings that mark the start of role-substantive content.
# When one of these appears anywhere in the description, we start the
# summary from the line AFTER it. Matched as whole-line headings
# (allowing punctuation + colons) — never as inline mentions.
_ROLE_ANCHORS_RE: Final = re.compile(
    r"^\s*"
    r"(your\s+role"
    r"|the\s+role"
    r"|about\s+the\s+role"
    r"|role\s+(description|overview|summary)"
    r"|job\s+(description|overview|summary|details|purpose)"
    r"|position\s+(description|overview|summary)"
    r"|what\s+you('?ll|\s+will)\s+do"
    r"|what\s+you\s+do"
    r"|responsibilities"
    r"|key\s+responsibilities"
    r"|main\s+responsibilities"
    r"|duties"
    r"|tasks\s+and\s+responsibilities"
    r"|الدور(\s+الوظيفي)?"
    r"|المهام(\s+و\s*المسؤوليات)?"
    r"|المسؤوليات(\s+الرئيسية)?"
    r"|الوصف\s+الوظيفي"
    r")\s*[:؟]?\s*$",
    re.IGNORECASE,
)

# Lines that indicate company-pitch boilerplate. When the description's
# FIRST non-empty line matches one of these, we skip the entire opening
# paragraph (everything until the first blank line or anchor) and start
# from there.
_COMPANY_INTRO_RE: Final = re.compile(
    r"^\s*"
    r"(about\s+(us|the\s+(company|organi[sz]ation)|"
    r"\w[\w\s\.&'-]{0,40}?)"  # "About <CompanyName>" — up to ~40 chars
    r"|who\s+we\s+are"
    r"|our\s+(company|story|mission)"
    r"|company\s+(overview|profile|description)"
    r"|نبذة\s+(عن(\s+الشركة)?|عنا)"
    r"|عن(ا)?\s+الشركة"  # noqa: RUF001 (Arabic letter alef intended)
    r"|من\s+نحن"
    r")\s*[:؟]?\s*$",
    re.IGNORECASE,
)


def _skip_company_intro(text: str) -> str:
    """Drop the leading "About Us / About the Company" block when present.

    Two passes:
      1. If a role-anchor heading appears anywhere, return everything
         AFTER that line.
      2. Else, if the very first non-empty line matches a company-intro
         heading OR pitch sentence, skip until the first blank line
         (paragraph break) or anchor heading.

    Returns the trimmed text. Always returns at least the original input
    when no boilerplate is detected.
    """
    raw_lines = text.splitlines()
    # Pass 1 — anchor match anywhere in the description
    for i, line in enumerate(raw_lines):
        if _ROLE_ANCHORS_RE.match(line):
            after = "\n".join(raw_lines[i + 1 :]).strip()
            if after:
                return after
            break  # anchor matched but nothing after → fall through

    # Pass 2 — first non-empty line is a company-intro heading or
    # opens with a pitch sentence ("X is the leading ...")
    first_nonempty_idx = next(
        (i for i, ln in enumerate(raw_lines) if ln.strip()), None
    )
    if first_nonempty_idx is None:
        return text
    first_line = raw_lines[first_nonempty_idx].strip()

    is_intro_heading = bool(_COMPANY_INTRO_RE.match(first_line))
    # Heuristic: company-pitch first sentence like
    # "Tamara is the leading fintech ..." / "We are a Saudi-based ..."
    is_pitch_sentence = bool(
        re.match(
            r"^(we\s+are\s+(a|the|an)\s|"
            r"\w[\w\s\.&'-]{1,60}\s+is\s+(a|the|an|leading|founded|building)\s)",
            first_line,
            re.IGNORECASE,
        )
    )
    if not (is_intro_heading or is_pitch_sentence):
        return text

    # Skip from the first_nonempty line until the next blank line OR
    # the next anchor heading. Then return everything after.
    j = first_nonempty_idx + 1
    while j < len(raw_lines):
        ln = raw_lines[j].strip()
        if not ln:
            j += 1
            break  # paragraph break — start summarising from j
        if _ROLE_ANCHORS_RE.match(ln):
            j += 1  # skip the anchor itself
            break
        j += 1
    rest = "\n".join(raw_lines[j:]).strip()
    return rest or text  # if we'd return empty, fall back to original


def _summarise_description(description: str | None) -> str | None:
    """Return the first 3-5 non-empty lines (~600 chars cap) of the
    description, skipping leading company-intro boilerplate.

    Saudi job posts typically open with "About Us / About the company"
    paragraphs — useful on the source page but pure noise in a job-feed
    channel. We try to jump past those and start at role-substantive
    content.

    Strategy:
      1. Defensive char strip (`_clean_text`).
      2. Find an explicit role-anchor heading ("Your Role", "About the
         Role", "Job Description", "Responsibilities", "What you'll do",
         Arabic equivalents). If found, start summarising AFTER it.
      3. Else, if the description opens with "About Us / About the
         company / Who we are" boilerplate, skip the first paragraph.
      4. Otherwise, take the first 3-5 non-empty lines as-is.
      5. Cap line count and total chars; ellipsis-truncate.
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
    text = _skip_company_intro(text)
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
        # eat the whole budget. When we truncate, prefer the last
        # sentence boundary inside the cap so we don't cut mid-word.
        if len(line) > 200:
            line = _truncate_at_sentence_boundary(line, 200)
        if running + len(line) > _SUMMARY_MAX_CHARS and picked:
            break
        picked.append(line)
        running += len(line) + 1  # +1 for the newline join
        if running >= _SUMMARY_MAX_CHARS:
            break

    # Trim trailing role-anchor headings with no body content
    # (e.g. summary ends with "Your Impact" or "Responsibilities"
    # because we picked up the next section's heading but the
    # cap fired before its body). Drop trailing heading-only lines
    # so the message doesn't end on a dangling header.
    while picked and (
        _ROLE_ANCHORS_RE.match(picked[-1]) or _looks_like_section_heading(picked[-1])
    ):
        picked.pop()

    if not picked:
        return None
    summary = "\n".join(picked)
    # Final hard cap — prefer sentence boundary at the cut point.
    if len(summary) > _SUMMARY_MAX_CHARS:
        summary = _truncate_at_sentence_boundary(summary, _SUMMARY_MAX_CHARS)
    return summary


def _looks_like_section_heading(line: str) -> bool:
    """Heuristic: short, Title-Case-ish, no ending punctuation, ≤6 words.

    Catches generic section labels like "Your Impact", "About You",
    "What You'll Do", "Required Skills", "Why Join Us" that aren't in
    `_ROLE_ANCHORS_RE`. Conservative: very short OR Title-Case OR
    ALL CAPS plus the no-ending-punctuation rule.
    """
    s = line.strip()
    if not s or len(s) > 60:
        return False
    if s[-1] in ".!?؟,:;":
        return False
    words = s.split()
    if len(words) > 6:
        return False
    # Title case (every word starts uppercase OR is a short article/prep)
    short_words = {"a", "an", "the", "of", "to", "in", "on", "for", "and", "or"}
    title_case = all(
        w[0].isupper() or w.lower() in short_words
        for w in words
        if w
    )
    if title_case:
        return True
    # ALL CAPS heading
    return s.upper() == s and any(c.isalpha() for c in s)


def _truncate_at_sentence_boundary(text: str, max_chars: int) -> str:
    """Cut `text` at-or-before `max_chars`, preferring a sentence end.

    Looks back from `max_chars` for the last `.`, `!`, `?`, or Arabic
    full-stop `؟`. Falls back to a word boundary; finally to a hard
    char cut. Appends an ellipsis unless the cut happens exactly at a
    natural sentence end.
    """
    if len(text) <= max_chars:
        return text
    head = text[: max_chars - 1]  # leave room for the ellipsis
    sentence_end = max(
        head.rfind("."), head.rfind("!"), head.rfind("?"), head.rfind("؟"),
    )
    if sentence_end >= max_chars // 2:
        # Stop right after the punctuation; keep the period itself.
        return head[: sentence_end + 1].rstrip()
    word_end = head.rfind(" ")
    if word_end >= max_chars // 2:
        return head[:word_end].rstrip() + "…"
    return head + "…"


def _humanise_posted_at(posted_at: object) -> str | None:
    """Render a datetime as an absolute date label, or None if missing.

    Absolute (not relative) so the date still makes sense when a
    subscriber scrolls back to an old post weeks later. Format:
    `Wed, 21 May 2026` — short weekday + day + month-name + year.

    Accepts `datetime` (tz-aware preferred; tz-naive coerced to UTC).
    Returns None for unknown / non-datetime inputs so the caller can
    skip the line entirely.
    """
    from datetime import UTC, datetime
    if posted_at is None or not isinstance(posted_at, datetime):
        return None
    ts = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=UTC)
    # `%-d` strips the leading zero from the day-of-month on glibc;
    # POSIX-portable alt: lstrip the zero from a `%d` formatted result.
    day = ts.strftime("%d").lstrip("0") or "0"
    return f"{ts.strftime('%a')}, {day} {ts.strftime('%b %Y')}"


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
    posted_at: object = None,
    url: str,
) -> tuple[str, list[tuple[str, str]]]:
    """Build the HTML-formatted message body + inline-button list.

    Returns `(body, buttons)`:
      * `body` — the HTML-formatted message text
      * `buttons` — list of `(label, url)` pairs to render as a row of
        tappable buttons below the message. Empty list when no URL.

    Caller is responsible for passing CLEAN already-stripped values —
    the runner already does this via `_clean_title` / `_clean_company_name`
    before calling us. `url` is the authoritative source URL.

    The title in the body is still rendered as a clickable link (for
    Telegram clients that hide the button row), AND the URL is shown
    in plain form at the bottom (for users who want to see / copy the
    actual URL). The new inline button gives a third affordance —
    a prominent tap-target that opens the job page.
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

    posted_label = _humanise_posted_at(posted_at)
    if posted_label:
        lines.append(f"📅 Posted {html.escape(posted_label)}")

    salary = _format_salary(salary_min, salary_max, salary_currency, salary_period)
    if salary:
        lines.append(f"💰 {html.escape(salary)}")

    summary = _summarise_description(description)
    if summary:
        # Blank line to visually separate the header from the body.
        lines.append("")
        lines.append(html.escape(summary))

    # NOTE: previously included a plain `🔗 URL` footer line. Removed
    # in v3 — three CTAs to the same URL (clickable title at top,
    # plain URL footer, inline button below) was redundant on mobile.
    # The title link + inline button are enough.

    # Hashtags for filtering. Limited to ones that are universally
    # safe (company slug can contain spaces / Arabic, so we slugify).
    tags: list[str] = []
    for raw in (company_name, category_code, city_name, country_code):
        s = _slug(raw)
        if s:
            tags.append(f"#{s}")
    if tags:
        lines.append("")  # blank line before tags for breathing room
        lines.append(" ".join(tags))

    buttons: list[tuple[str, str]] = []
    if url:
        buttons.append(("👀 View full job", url))

    return "\n".join(lines), buttons
