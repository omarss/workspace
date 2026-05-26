"""SA + GCC location filter.

Used by the runner to drop postings from ATS crawlers (Greenhouse, Lever,
Workable, SmartRecruiters, Workday, SuccessFactors) whose only output is a
global board — we ingest just the GCC slice.

Boards (Bayt, Naukrigulf, Wuzzuf, LinkedIn) are already SA-scoped at the
search URL level, so the filter is a redundant safety check there.

GCC = Saudi Arabia, UAE, Bahrain, Kuwait, Qatar, Oman.
"""

from __future__ import annotations

import re
from typing import Final

# ISO-3166 alpha-2 codes for the GCC.
_GCC_COUNTRY_CODES: Final[frozenset[str]] = frozenset({
    "sa", "ae", "bh", "kw", "qa", "om",
})

# All city / country names (Latin + Arabic) that mark a posting as GCC.
# Stored as lowercase plain text; we match with simple `in`-checks after
# casefolding. The list is intentionally generous — false-positives are
# acceptable (a posting that *might* be GCC is kept), false-negatives are
# the real cost (we drop a real SA job because the location was weird).
_GCC_MARKERS_EN: Final[tuple[str, ...]] = (
    # --- Saudi Arabia ---
    "saudi arabia", "saudi-arabia", "saudi", "ksa", "kingdom of saudi",
    "riyadh", "jeddah", "jiddah", "dammam", "khobar", "dhahran", "jubail",
    "yanbu", "tabuk", "abha", "taif", "ta'if", "buraydah", "ar-rass",
    "ar rass", "hofuf", "hail", "ha'il", "najran", "jazan", "khamis mushait",
    "neom", "qatif", "al ahsa", "al-ahsa", "al kharj", "khamis", "mecca",
    "makkah", "madinah", "medina",
    # --- UAE ---
    "united arab emirates", "uae", "u.a.e", "emirates",
    "dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah",
    "ras-al-khaimah", "fujairah", "umm al quwain", "umm-al-quwain",
    # --- Bahrain ---
    "bahrain", "manama", "riffa",
    # --- Kuwait ---
    "kuwait", "kuwait city",
    # --- Qatar ---
    "qatar", "doha",
    # --- Oman ---
    "oman", "muscat", "salalah", "sohar",
)
_GCC_MARKERS_AR: Final[tuple[str, ...]] = (
    # Saudi
    "السعودية", "المملكة العربية السعودية", "الرياض", "جدة", "جده",
    "الدمام", "الخبر", "الظهران", "تبوك", "أبها", "ابها", "الطائف",
    "بريدة", "بريده", "ينبع", "حائل", "نجران", "جازان", "مكة", "المدينة",
    "المدينة المنورة", "نيوم", "القصيم",
    # UAE
    "الإمارات", "الامارات", "دبي", "أبوظبي", "ابوظبي", "الشارقة",
    "عجمان", "رأس الخيمة", "الفجيرة",
    # Bahrain
    "البحرين", "المنامة",
    # Kuwait
    "الكويت",
    # Qatar
    "قطر", "الدوحة",
    # Oman
    "عُمان", "عمان", "مسقط", "صلالة",
)

# A regex that matches the EN markers with word boundaries (to avoid e.g.
# "muscatel wine" tripping on "muscat"). Built once at import.
_EN_REGEX: Final[re.Pattern[str]] = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in _GCC_MARKERS_EN) + r")\b",
    re.IGNORECASE,
)


def is_gcc_location(
    raw_location: str | None,
    *,
    country_code: str | None = None,
) -> bool:
    """Return True when the posting belongs to a GCC country.

    Semantics (intentionally conservative — false negatives are cheaper
    than false positives here):

      * `raw_location` contains a recognised GCC city / country marker → True
      * `country_code` is a trusted ISO-3166 code AND raw_location is empty
        (we can't otherwise tell) → True only if code is in GCC set
      * Anything else (Remote-only, empty, non-GCC city)               → False

    The `country_code` arg is treated as a *fallback*, never as a shortcut,
    because the upstream `ParsedPosting.country_code` defaults to "sa" and
    so isn't trustworthy on its own.
    """
    if raw_location:
        # Location string is present: match against GCC markers; if it
        # mentions a non-GCC place we drop, ignoring country_code.
        return bool(_EN_REGEX.search(raw_location)) or any(
            marker in raw_location for marker in _GCC_MARKERS_AR
        )
    # raw_location is empty. The historic fallback "trust country_code"
    # was too permissive: `ParsedPosting.country_code` defaults to "sa"
    # in the dataclass, so parsers that fail to extract a location AND
    # don't override the default would always pass the GCC gate. Live
    # leak: SABIC's career site landed Bangalore / Bergen-Op-Zoom /
    # Pontirolo roles in the SA-focused corpus because their parser
    # left raw_location null. We now only trust `country_code` when
    # it's explicitly NOT the default "sa" — that means a Cisco-style
    # JSON-LD parser that sets country_code='ae' (or 'us', 'in', ...)
    # still gets evaluated, but the silent default-sa path is shut.
    if country_code is None:
        return False
    code = country_code.lower()
    if code == "sa":
        # Could be default OR explicit "sa". Without a raw_location to
        # confirm, treat as untrustworthy and drop.
        return False
    return code in _GCC_COUNTRY_CODES


# ---------------------------------------------------------------------------
# Plain-SQL counterpart — used by the one-shot purge below.
# ---------------------------------------------------------------------------
PURGE_WHERE_SQL: Final[str] = """
    NOT (
        country_code IN ('sa','ae','bh','kw','qa','om')
        OR LOWER(COALESCE(raw_location, '')) ~
           '\\m(saudi|ksa|riyadh|jeddah|jiddah|dammam|khobar|dhahran|jubail|yanbu|tabuk|abha|taif|buraydah|hofuf|hail|najran|jazan|neom|makkah|mecca|madinah|medina|united arab emirates|uae|emirates|dubai|abu dhabi|sharjah|ajman|ras al khaimah|fujairah|umm al quwain|bahrain|manama|riffa|kuwait|qatar|doha|oman|muscat|salalah|sohar)\\M'
        OR COALESCE(raw_location, '') LIKE '%السعودية%'
        OR COALESCE(raw_location, '') LIKE '%الرياض%'
        OR COALESCE(raw_location, '') LIKE '%جدة%'
        OR COALESCE(raw_location, '') LIKE '%الدمام%'
        OR COALESCE(raw_location, '') LIKE '%الخبر%'
        OR COALESCE(raw_location, '') LIKE '%مكة%'
        OR COALESCE(raw_location, '') LIKE '%المدينة%'
        OR COALESCE(raw_location, '') LIKE '%الإمارات%'
        OR COALESCE(raw_location, '') LIKE '%دبي%'
        OR COALESCE(raw_location, '') LIKE '%أبوظبي%'
        OR COALESCE(raw_location, '') LIKE '%البحرين%'
        OR COALESCE(raw_location, '') LIKE '%الكويت%'
        OR COALESCE(raw_location, '') LIKE '%قطر%'
        OR COALESCE(raw_location, '') LIKE '%عمان%'
    )
"""
