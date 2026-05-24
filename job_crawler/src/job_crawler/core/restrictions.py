"""Heuristic detection of posting restrictions: Saudi-only and gender-only.

Pure functions — no I/O, no globals. Safe to call on every parse.
The phrase lists are intentionally small and conservative; false positives
are worse here than false negatives (the cluster verdict reflects them).
"""

from __future__ import annotations

import re
from typing import Final

from job_crawler_db import GenderPreference

# ---------------------------------------------------------------------------
# Saudi-only detection
# ---------------------------------------------------------------------------
# English: phrase must explicitly restrict to Saudi nationals/citizens.
# Arabic:  للسعوديين فقط (literally "for Saudis only"), سعوديين فقط, etc.
# We require the "only" qualifier so a posting that merely *prefers* Saudis
# is not mis-flagged.

_SA_ONLY_EN_PHRASES: tuple[str, ...] = (
    "saudi nationals only",
    "saudis only",
    "saudi national only",
    "saudi citizens only",
    "only saudi nationals",
    "open to saudi nationals only",
    "open to saudis only",
    "for saudi nationals only",
    "only for saudi nationals",
    "saudi only",
)

_SA_ONLY_AR_PHRASES: tuple[str, ...] = (
    "للسعوديين فقط",
    "للسعوديات فقط",
    "للسعوديين والسعوديات فقط",
    "للسعودي فقط",
    "السعوديين فقط",
    "سعوديي الجنسية فقط",
    "للجنسية السعودية فقط",
)


def detect_saudi_only(text: str | None) -> bool:
    """True when `text` explicitly restricts the role to Saudi nationals."""
    if not text:
        return False
    lower = text.casefold()
    if any(p in lower for p in _SA_ONLY_EN_PHRASES):
        return True
    return any(p in text for p in _SA_ONLY_AR_PHRASES)


# ---------------------------------------------------------------------------
# Gender preference detection
# ---------------------------------------------------------------------------
# Same conservative principle. Single-gender restrictions are common in SA
# retail / hospitality / education roles.

_FEMALE_EN_PHRASES: tuple[str, ...] = (
    "female candidates only", "females only", "for females only",
    "open to females only", "open to female candidates only",
    "female only", "women only", "for women only",
    "this position is for females",
)
_MALE_EN_PHRASES: tuple[str, ...] = (
    "male candidates only", "males only", "for males only",
    "open to males only", "open to male candidates only",
    "male only", "men only", "for men only",
    "this position is for males",
)
_FEMALE_AR_PHRASES: tuple[str, ...] = (
    "للنساء فقط", "للإناث فقط", "للسيدات فقط",
    "للمتقدمات فقط", "للمرشحات فقط",
)
_MALE_AR_PHRASES: tuple[str, ...] = (
    "للرجال فقط", "للذكور فقط",
    "للمتقدمين فقط", "للمرشحين فقط",
)


# A loose word-boundary regex catches inflected forms like
# "Female Customer Service Representatives only" without false-positive
# matching of "female" inside e.g. "femaleness" or random tokens.
_FEMALE_LOOSE: Final = re.compile(
    r"\b(female|women)\b[^.!?]{0,40}\bonly\b",
    re.IGNORECASE,
)
_MALE_LOOSE: Final = re.compile(
    r"\b(male|men)\b[^.!?]{0,40}\bonly\b",
    re.IGNORECASE,
)


def detect_gender_preference(text: str | None) -> GenderPreference:
    """Return the gender restriction declared in `text`, or `any` when none."""
    if not text:
        return GenderPreference.any
    lower = text.casefold()
    # Use word-bounded match so "male" doesn't match the "male" inside
    # "female" (a real bug if you `in`-check raw substrings).
    female = (
        _any_word(lower, _FEMALE_EN_PHRASES)
        or any(p in text for p in _FEMALE_AR_PHRASES)
        or bool(_FEMALE_LOOSE.search(text))
    )
    male = (
        _any_word(lower, _MALE_EN_PHRASES)
        or any(p in text for p in _MALE_AR_PHRASES)
        or bool(_MALE_LOOSE.search(text))
    )
    if female and not male:
        return GenderPreference.female_only
    if male and not female:
        return GenderPreference.male_only
    # If both fire (e.g. "no preference between male only / female only…"),
    # treat as no restriction — better than picking the wrong one.
    return GenderPreference.any


def _any_word(text: str, phrases: tuple[str, ...]) -> bool:
    """True when any of `phrases` appears in `text` with leading + trailing
    word boundaries. Prevents `male` matching inside `female`."""
    return any(re.search(rf"\b{re.escape(p)}\b", text) for p in phrases)
