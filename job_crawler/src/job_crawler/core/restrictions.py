"""Heuristic detection of posting restrictions: Saudi-only and gender-only.

Pure functions — no I/O, no globals. Safe to call on every parse.
The phrase lists are intentionally small and conservative; false positives
are worse here than false negatives (the cluster verdict reflects them).
"""

from __future__ import annotations

import re
from typing import Final

from job_crawler_db import ExperienceLevel, GenderPreference

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


# ---------------------------------------------------------------------------
# Experience-level detection
# ---------------------------------------------------------------------------
# Maps title / body keywords to the closest `ExperienceLevel` enum value.
# Each tier is mutually exclusive in the title; if the title carries no
# signal, the body's first-paragraph keywords are checked as a fallback.
# Conservative: when two tiers fire (e.g. "Senior Engineer / Lead Role")
# we return None and let the value stay NULL.

# Downgrade modifiers ALWAYS win — "Associate Product Manager" is a
# junior PM, not a manager. Scan these first; only fall through to the
# rank-ordered patterns when no downgrade is present.
_EXP_LEVEL_DOWNGRADE_PATTERNS: Final[tuple[tuple[ExperienceLevel, re.Pattern[str]], ...]] = (
    (ExperienceLevel.junior, re.compile(r"\b(junior|jr\.?|associate)\b", re.IGNORECASE)),
    (ExperienceLevel.entry,  re.compile(r"\b(entry[- ]level|intern|graduate|trainee|fresh(er)?)\b", re.IGNORECASE)),
)

# Highest-rank wins among non-downgrade modifiers. "Senior Engineering
# Manager" is a manager because manager is a higher rank than senior.
_EXP_LEVEL_RANK_PATTERNS: Final[tuple[tuple[ExperienceLevel, re.Pattern[str]], ...]] = (
    (ExperienceLevel.executive, re.compile(r"\b(chief|cxo|cto|cfo|ceo|coo|cmo|cpo|vp)\b", re.IGNORECASE)),
    (ExperienceLevel.director,  re.compile(r"\b(director|head of)\b", re.IGNORECASE)),
    (ExperienceLevel.manager,   re.compile(r"\b(manager|supervisor)\b", re.IGNORECASE)),
    (ExperienceLevel.lead,      re.compile(r"\b(lead|principal|staff)\b", re.IGNORECASE)),
    (ExperienceLevel.senior,    re.compile(r"\b(senior|sr\.?)\b", re.IGNORECASE)),
)


def detect_experience_level(
    title: str | None,
    description: str | None = None,
) -> ExperienceLevel | None:
    """Return the strongest experience-level signal in the title.

    Order of checks (first-match-wins per group):
      1. Downgrade modifiers (associate / junior / intern / graduate)
         on the title — these ALWAYS win, so "Associate PM" → junior,
         "Graduate Engineer" → entry.
      2. Highest-rank pattern in the title (executive > director >
         manager > lead > senior) — so "Senior Engineering Manager"
         is a manager.
      3. Same two passes on the first 500 chars of the description as
         a fallback when the title is silent.
    """
    sources = (title, (description or "")[:500])
    for src in sources:
        if not src:
            continue
        for level, pattern in _EXP_LEVEL_DOWNGRADE_PATTERNS:
            if pattern.search(src):
                return level
        for level, pattern in _EXP_LEVEL_RANK_PATTERNS:
            if pattern.search(src):
                return level
    return None


# ---------------------------------------------------------------------------
# Arabic-required detection
# ---------------------------------------------------------------------------
# Conservative — only fires when "Arabic" appears alongside a "required /
# native / fluent / mandatory" qualifier. Real postings always couch the
# language requirement explicitly, so loose substring matching ("Arabic"
# alone) would false-positive on the half of SA postings that merely
# mention "Arabic speakers welcome" as a preference.

_REQ_ARABIC_EN_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bnative\s+arabic\b", re.IGNORECASE),
    re.compile(r"\barabic\s+(speaker|native)\b", re.IGNORECASE),
    re.compile(r"\bfluen(t|cy)\s+in\s+arabic\b", re.IGNORECASE),
    re.compile(r"\barabic\s+is\s+(required|mandatory|a\s+must)\b", re.IGNORECASE),
    re.compile(r"\b(must|should|need to)\s+speak\s+arabic\b", re.IGNORECASE),
    re.compile(r"\barabic\s+language\s+(required|skills?|proficiency)\b", re.IGNORECASE),
    re.compile(r"\bproficien(t|cy)\s+in\s+arabic\b", re.IGNORECASE),
    re.compile(r"\bbilingual\s+\(?(arabic|english\s*[/,]\s*arabic|arabic\s*[/,]\s*english)\)?", re.IGNORECASE),
)

_REQ_ARABIC_AR_PHRASES: Final[tuple[str, ...]] = (
    "إتقان اللغة العربية",
    "إجادة اللغة العربية",
    "اللغة العربية مطلوبة",
    "متحدث باللغة العربية",
    "متحدثة باللغة العربية",
    "اللغة الأم العربية",
)


def detect_requires_arabic(text: str | None) -> bool | None:
    """True when the role explicitly requires Arabic fluency.

    Returns None when the text doesn't mention Arabic at all (so the
    cluster stays NULL rather than getting an explicit False on every
    Arabic-silent description — which would be misleading on a Saudi
    board). Returns True only when a phrase explicitly qualifies the
    language as required.
    """
    if not text:
        return None
    if any(p.search(text) for p in _REQ_ARABIC_EN_RES):
        return True
    if any(p in text for p in _REQ_ARABIC_AR_PHRASES):
        return True
    # Mentions Arabic at all? Return None (unknown) — there's a signal,
    # but not enough to call it required. Otherwise return None too
    # (truly silent on the topic). Both paths converge to None.
    return None


# ---------------------------------------------------------------------------
# Visa sponsorship detection
# ---------------------------------------------------------------------------
# Two-state: explicit yes (sponsorship offered) → True; explicit no
# (must have own visa / iqama transfer required) → False; silent → None.

_VISA_YES_EN_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bvisa\s+sponsorship\b", re.IGNORECASE),
    re.compile(r"\bwe\s+(will\s+)?sponsor\s+(your\s+)?(work\s+)?visas?\b", re.IGNORECASE),
    re.compile(r"\bsponsor(s|ed|ship)?\s+(work|employment|h-?1b|gcc)\s*visas?\b", re.IGNORECASE),
    re.compile(r"\biqama\s+(will\s+be\s+)?provided\b", re.IGNORECASE),
    re.compile(r"\bemployer\s+(provides?|sponsors?)\s+(visa|iqama)\b", re.IGNORECASE),
)

_VISA_NO_EN_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(must\s+have|requires?)\s+(transferable\s+)?iqama\b", re.IGNORECASE),
    re.compile(r"\bno\s+visa\s+sponsorship\b", re.IGNORECASE),
    re.compile(r"\bdoes\s+not\s+offer\s+(visa\s+)?sponsorship\b", re.IGNORECASE),
    re.compile(r"\bown\s+(valid\s+)?iqama\b", re.IGNORECASE),
    re.compile(r"\b(iqama|residence\s+permit)\s+(transferable|transfer)\b", re.IGNORECASE),
)


def detect_visa_sponsorship(text: str | None) -> bool | None:
    """Three-state visa-sponsorship signal.

    Returns True when the posting explicitly offers sponsorship, False
    when it requires the candidate to bring their own iqama / residence,
    and None when silent (or contradictory).

    Implementation note: the YES regexes catch the substring "visa
    sponsorship" in isolation, but the NO regex "no visa sponsorship"
    contains that same substring. To avoid every NO match also firing a
    YES match, we drop YES spans that are fully contained inside a NO
    span before deciding. True contradictions (one YES somewhere AND
    one NO elsewhere) still resolve to None.
    """
    if not text:
        return None
    yes_spans = [m.span() for p in _VISA_YES_EN_RES for m in p.finditer(text)]
    no_spans = [m.span() for p in _VISA_NO_EN_RES for m in p.finditer(text)]
    yes_real = [
        y for y in yes_spans
        if not any(n[0] <= y[0] and y[1] <= n[1] for n in no_spans)
    ]
    if yes_real and no_spans:
        return None  # signals truly contradict each other
    if yes_real:
        return True
    if no_spans:
        return False
    return None
