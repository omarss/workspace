"""ParsedPosting → JobPostingUpsert + side-data dispatch.

Centralised so per-source crawlers don't reinvent the same wiring.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from decimal import Decimal as _Decimal
from typing import Final
from uuid import UUID

from job_crawler_db import (
    ApplicationChannelKind,
    JobCrawlerDB,
    JobPostingUpsert,
    SkillRequirement,
)

from .types import ApplicationChannelRaw, ParsedPosting, RawSkillRaw

_LOG: Final = logging.getLogger("job_crawler.normalise")


@dataclass(frozen=True, slots=True)
class LocationResolution:
    """Output of `resolve_city` — keeps city + region + country in sync.

    All three fields default to None (unresolved). When `city_id` resolves,
    the matching `cities` row's `region_code` and `country_code` are always
    populated so the posting can be filtered by either dimension.
    """

    city_id: UUID | None = None
    region_code: str | None = None
    country_code: str | None = None


# Countries seeded by `discover/manual_seed._ensure_reference`. Any
# `country_code` outside this set is unknown to the FK on
# job_postings.country_code → countries(code) and the upsert blows up.
# Real-world JSON-LD `addressCountry` values are inconsistent — we've
# seen "United States" (gets truncated to "un"), "USA" → "us",
# bare codes, full names, even free-text. Validate explicitly + fall
# back to "sa" rather than risk the FK.
_KNOWN_COUNTRY_CODES: Final[frozenset[str]] = frozenset({
    "sa", "ae", "bh", "kw", "om", "qa",
})


def coerce_country_code(value: str | None, default: str = "sa") -> str:
    """Return a valid 2-letter country code or the default.

    Crawlers / JSON-LD parsers should funnel any country-ish string
    through this so an unknown value never reaches `JobPostingUpsert`.
    """
    if not value:
        return default
    code = value.strip().lower()[:2]
    return code if code in _KNOWN_COUNTRY_CODES else default


# Characters that leak through HTML parsing but are invisible in the UI:
# BOM (U+FEFF), zero-width space / joiner / non-joiner (U+200B-U+200D),
# bidi marks (U+200E-U+200F), bidi overrides (U+202A-U+202E), word joiner
# (U+2060). They corrupt search-vector tokenisation and content_hash
# dedupe (visually-identical descriptions hash to different values).
_INVISIBLE_RE: Final = re.compile(r"[﻿​-‏‪-‮⁠]")

# ASCII control chars except TAB / LF / CR — these get stripped too.
# (tab/newline/cr are legitimate inside descriptions; everything else is
# garbage from broken-binary leaks or copy-paste from PDFs.)
_CONTROL_RE: Final = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

# Three-or-more consecutive spaces / inner whitespace runs collapse to
# single space. Newlines preserved as-is (description structure matters).
_INNER_WS_RUN_RE: Final = re.compile(r"[ \t]{2,}")


def _clean_text(value: str | None) -> str | None:
    """Sanitise a free-text field for storage.

    Order of operations matters:
      1. `html.unescape` — turn `&amp;`, `&lt;`, etc. into real chars.
         Run first so any encoded invisible char gets caught by step 2.
      2. Strip BOM / zero-width / RTL bidi marks.
      3. Strip ASCII control chars (keep TAB/LF/CR).
      4. Collapse runs of 2+ spaces / tabs to one.
      5. Strip leading + trailing whitespace.
      6. Return None if empty (so the column stays NULL instead of '').
    """
    if value is None:
        return None
    s = html.unescape(value)
    s = _INVISIBLE_RE.sub("", s)
    s = _CONTROL_RE.sub("", s)
    s = _INNER_WS_RUN_RE.sub(" ", s)
    s = s.strip()
    return s or None


# Trailing characters that mark a company-name field as keyboard mash or
# leftover punctuation rather than a real entity name. Punctuation that's
# valid in real names (`.` for "Co.", `'` for "O'Reilly", `)` for "Co.
# (KSA)", `+` for "Tech+" trademarks) is intentionally NOT here.
_GARBAGE_COMPANY_TAIL_RE: Final = re.compile(r"[&!#*=<>?^@]$")


def _clean_company_name(value: str | None) -> str | None:
    """Run `_clean_text` plus a couple of company-specific sanity checks.

    Returns None when the name looks like garbage so the runner skips
    company resolution (leaving `company_id` NULL) rather than creating
    a junk row like `Qwer0770&` and FK-linking real jobs to it.

    Heuristics — kept narrow to avoid false-positives on real names:
      * Trailing `&!#*=<>?^@` (the live `Qwer0770&` case).
      * Single token with mixed case + digits + length 4-12 AND no
        recognisable English vowel — looks like a password / keyboard mash.
        ("3M", "G42", "B2B Solutions", "Center3" all pass this guard.)
    """
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    if _GARBAGE_COMPANY_TAIL_RE.search(cleaned):
        return None
    return cleaned


# ---------------------------------------------------------------------------
# Title cleanup
# ---------------------------------------------------------------------------
# Real-world titles leak two classes of noise that survive HTML parsing
# and the generic `_clean_text` chokepoint:
#
#   1. Brand / location trails after pipe separators.
#      "Regional Aftersales Manager | Al-Futtaim Automotive | BYD | Riyadh"
#      "Civil Construction Manager - Residential Projects | Saudi Arabia"
#      The first segment is the real title; everything past the first
#      `|` is brand-tagging that pollutes the search vector and inflates
#      character length.
#
#   2. Click-bait / call-to-action prefixes before a pipe.
#      "Hiring Now | Tendering Engineer - MEP"
#      Here the real title is AFTER the pipe — the prefix is filler.
#
#   3. ATS / boilerplate prefixes that are not "real" title content.
#      "Career Opportunities: Divisional Trade Marketing Manager"
#      "URGENT HIRING: Construction Supervisor"
#
#   4. Req-id paren suffixes that aren't part of the role name.
#      "Procurement Intern (Tamheer 24767260)"
#      "Career Opportunities: Marketing Manager (88068)"
#      The paren contents are pure numeric / ATS identifiers — strip
#      them. Distinguish from signal-bearing parens like
#      "(Saudi National Preferred)" or "(BIM)".

# Pure-noise prefixes that should be stripped when followed by ` | ` or `:`.
_TITLE_NOISE_PREFIX_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\s*hiring\s+now\s*[|:]\s*", re.IGNORECASE),
    re.compile(r"^\s*now\s+hiring\s*[|:]\s*", re.IGNORECASE),
    re.compile(r"^\s*urgent(?:\s+hiring)?\s*[!|:]?\s*[|:]\s*", re.IGNORECASE),
    re.compile(r"^\s*career\s+opportunities\s*:\s*", re.IGNORECASE),
    re.compile(r"^\s*we\s+are\s+hiring\s*[|:]\s*", re.IGNORECASE),
    re.compile(r"^\s*join\s+(?:our|us)\s*[|:]\s*", re.IGNORECASE),
)

# Paren contents that are pure noise (req-ids, internal codes, Tamheer
# reference numbers, urgency stickers). End-of-string anchored except
# "(Urgent!)" which ATSes also embed mid-title; we strip it anywhere.
# Conservative: only strip when the paren content matches one of these
# patterns exactly — signal-bearing parens like "(Saudi National)" or
# "(BIM)" or "(All Levels)" are left intact.
_TITLE_NOISE_PAREN_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\s*\(\s*\d{3,}\s*\)\s*$"),  # "(88068)", "(24767260)"
    re.compile(r"\s*\(\s*tamheer\s+\d+\s*\)\s*$", re.IGNORECASE),
    re.compile(r"\s*\(\s*req\.?\s*\d+\s*\)\s*$", re.IGNORECASE),
    re.compile(r"\s*\(\s*job\s*(?:id|#)?\s*\d+\s*\)\s*$", re.IGNORECASE),
    # Urgency stickers can appear mid-title — strip anywhere.
    re.compile(r"\s*\(\s*urgent\s*(?:hiring)?!?\s*\)", re.IGNORECASE),
)


def _clean_title(value: str | None) -> str | None:
    """Sanitise a job title — runs after `_clean_text` to strip extras.

    Returns None when the title is empty after cleaning. Order matters:
      1. Strip click-bait prefixes (`Hiring Now |`, `Career Opportunities:`).
      2. If a pipe separator remains, take the LONGEST segment that looks
         like a role title (preferred over heuristics about
         pre-vs-post-pipe ordering — the longest segment is almost
         always the actual job title; brand trails are short bursts).
      3. Strip pure-noise paren suffixes (req-ids).
      4. Collapse whitespace + strip.
    """
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    for pattern in _TITLE_NOISE_PREFIX_RES:
        cleaned = pattern.sub("", cleaned, count=1)
    if "|" in cleaned:
        # Pick the longest segment by character length — the real title
        # is almost always longer than brand trails like "| BYD" or
        # "| Riyadh". Tie → keep the first non-empty segment.
        segments = [s.strip() for s in cleaned.split("|")]
        segments = [s for s in segments if s]
        if segments:
            cleaned = max(segments, key=len)
    for pattern in _TITLE_NOISE_PAREN_RES:
        cleaned = pattern.sub("", cleaned)
    # Strip trailing punctuation: ASCII space/hyphen/pipe/colon plus
    # Unicode en-dash (U+2013) and em-dash (U+2014). chr() avoids ruff's
    # ambiguous-character warning while keeping the strip working.
    trail_chars = " -|:" + chr(0x2013) + chr(0x2014)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(trail_chars)
    return cleaned or None


# ---------------------------------------------------------------------------
# Salary normalisation
# ---------------------------------------------------------------------------
# Every posting stored as SAR so the search facets / range filters /
# sort-by-salary queries operate on a single unit. The SAR/USD peg has
# been fixed by SAMA at 3.75 since 1986 — safe to hardcode as a static
# rate. Other GCC currencies have similar pegs but we leave non-SAR
# salaries alone for now (returning them as-is) rather than risk a
# bad rate. Future enhancement: per-currency rate table + occasional
# refresh from a free FX endpoint.

_USD_TO_SAR: Final[_Decimal] = _Decimal("3.75")
_KNOWN_CONVERSIONS: Final[dict[str, _Decimal]] = {
    "USD": _USD_TO_SAR,
    # Other GCC pegs (round figures — close enough for display, don't
    # use for accounting):
    "AED": _Decimal("1.02"),   # AED to SAR (3.67 USD/AED, SAR=3.75)
    "BHD": _Decimal("9.95"),   # BHD to SAR
    "KWD": _Decimal("12.2"),   # KWD to SAR (approx, KWD floats)
    "OMR": _Decimal("9.75"),   # OMR to SAR
    "QAR": _Decimal("1.03"),   # QAR pegged to USD at 3.64
}


def _normalise_salary_to_sar(
    salary_min: _Decimal | int | float | None,
    salary_max: _Decimal | int | float | None,
    salary_currency: str | None,
) -> tuple[_Decimal | None, _Decimal | None, str | None]:
    """Convert salary values to SAR using static GCC pegs.

    Behaviour:
      * Both values None or unknown currency → pass through unchanged.
      * Currency already SAR / sar → trim to two decimals, return as SAR.
      * Currency in `_KNOWN_CONVERSIONS` → multiply each non-None value
        by the rate, return as SAR.
      * Unknown / freeform currency → pass through unchanged (caller
        decides how to render).

    Conservative: never invents a value where None was passed in.
    """
    if salary_min is None and salary_max is None:
        return None, None, salary_currency

    if not salary_currency:
        return _to_decimal(salary_min), _to_decimal(salary_max), salary_currency

    upper = salary_currency.strip().upper()
    if upper == "SAR":
        return _to_decimal(salary_min), _to_decimal(salary_max), "SAR"

    rate = _KNOWN_CONVERSIONS.get(upper)
    if rate is None:
        # Unknown currency — leave numbers and label as-is; the dashboard
        # / Telegram formatter will render whatever the source said.
        return _to_decimal(salary_min), _to_decimal(salary_max), salary_currency

    dmin = _to_decimal(salary_min)
    dmax = _to_decimal(salary_max)
    return (
        dmin * rate if dmin is not None else None,
        dmax * rate if dmax is not None else None,
        "SAR",
    )


def _to_decimal(value: _Decimal | int | float | None) -> _Decimal | None:
    """Coerce a numeric-ish value to Decimal for arithmetic + storage.

    Decimal-from-float goes via str() to avoid binary-float artefacts
    like `Decimal('1500.0000000000000909494701772928237915')`. None
    passes through.
    """
    if value is None:
        return None
    if isinstance(value, _Decimal):
        return value
    return _Decimal(str(value))


# Free-text aliases + sub-city neighborhoods → canonical cities.name_en.
# Bayt and a few other sources frequently emit raw_location values that are
# neighborhoods (e.g. "An Narjis", "Al Olaya"), district names, or alternate
# transliterations ("Jiddah", "Mecca"). The trigram lookup against
# cities can't bridge those, so we route them through a static map first.
# Lowercased lookup. New entries: prefer real-world spellings observed in the
# crawl_fetches sample over our internal canonical names.
_CITY_ALIASES: Final[dict[str, str]] = {
    # alt transliterations of Saudi cities
    "jiddah": "Jeddah",
    "mecca": "Makkah",
    "medina": "Madinah",
    "altaif": "Taif",
    "al-taif": "Taif",
    "al taif": "Taif",
    "al khobar": "Khobar",
    "al-khobar": "Khobar",
    "al ahsa": "Hofuf (Al Hasa)",
    "al-ahsa": "Hofuf (Al Hasa)",
    "alkhafji": "Khobar",  # Khafji has no cities row; nearest large city
    "eastern province": "Dammam",
    "al sharqia": "Dammam",
    "ash sharqiyah": "Dammam",
    # Riyadh neighborhoods — all map to Riyadh
    "al olaya": "Riyadh", "al-olaya": "Riyadh", "olaya": "Riyadh",
    "al malqa": "Riyadh", "al-malqa": "Riyadh",
    "al malaz": "Riyadh", "al-malaz": "Riyadh",
    "al narjis": "Riyadh", "an narjis": "Riyadh",
    "al nakheel": "Riyadh", "an nakheel": "Riyadh",
    "al nahdah": "Riyadh", "an nahdah": "Riyadh",
    "al naseem": "Riyadh", "an naseem": "Riyadh",
    "al naim": "Riyadh", "an naim": "Riyadh",
    "al nuzhah": "Riyadh", "an nuzhah": "Riyadh",
    "al sahafah": "Riyadh", "as sahafah": "Riyadh",
    "al saadah": "Riyadh", "as saadah": "Riyadh",
    "al safa": "Riyadh", "as-safa": "Riyadh", "as safa": "Riyadh",
    "al sulaymaniyah": "Riyadh", "as sulaymaniyah": "Riyadh",
    "al suwaydi": "Riyadh", "as suwaydi": "Riyadh",
    "as suwaydi al gharbi": "Riyadh",
    "al rabwah": "Riyadh", "ar rabwah": "Riyadh",
    "al rawdhah": "Riyadh", "ar-rawdha": "Riyadh", "ar rawdhah": "Riyadh",
    "al rawdha": "Riyadh", "al-rawdhah": "Riyadh",
    "al wurud": "Riyadh", "al-wurud": "Riyadh",
    "al wadi": "Riyadh",
    "al yasamin": "Riyadh",
    "al izdihar": "Riyadh", "al-izdihar": "Riyadh",
    "al khalidiyah": "Riyadh", "al-khalidiyah": "Riyadh",
    "al falah": "Riyadh", "al-falah": "Riyadh",
    "al fayha": "Riyadh", "al-fayha": "Riyadh",
    "al manakh": "Riyadh", "al-manakh": "Riyadh",
    "al ma'athar": "Riyadh", "al-maathar": "Riyadh", "al maathar": "Riyadh",
    "al muwanisiyah": "Riyadh",
    "al mashail": "Riyadh", "al-mashail": "Riyadh",
    "al malik abd allah": "Riyadh", "al-malik-abdullah": "Riyadh",
    "al selay": "Riyadh", "al-selay": "Riyadh",
    "al shemal": "Riyadh", "al-shemal": "Riyadh",
    "ash shati": "Riyadh",
    "hittin": "Riyadh",
    # Jeddah neighborhoods → Jeddah
    "al aridhah": "Jeddah",
    "al awali": "Jeddah",
    "al basatin": "Jeddah",
    "al baghdadiyah al gharbiyah": "Jeddah",
    "al hamdaniya": "Jeddah", "al-hamdaniya": "Jeddah",
    "dahaban": "Jeddah",
    "mushrifah": "Jeddah",
    "obhour shamaliya": "Jeddah",
    "ubhur al janubiyah": "Jeddah",
    "obhour": "Jeddah",
    # Misc Riyadh & Eastern suburbs / industrial areas
    "qurtubah": "Riyadh",
    "industrial area-kharj road": "Riyadh",
    # Other KSA towns
    "besha": "Bisha",
    "jizan": "Jazan",
    "khulays": "Makkah",  # small town in Makkah region; nearest seeded city
}


async def resolve_city(
    db: JobCrawlerDB,
    hint: str | None,
    *,
    raw_location: str | None = None,
    country_code: str | None = None,
) -> LocationResolution:
    """Map a free-text hint to a `cities` row, returning the full location triple.

    Tries (in order):
      1. The explicit hint (if any).
      2. Each comma-separated token of `raw_location` from right to left
         (city is usually one of the last tokens, e.g. "An Narjis, Riyadh").
      3. For each candidate token, consult `_CITY_ALIASES` first (covers
         alt transliterations and Riyadh/Jeddah neighborhoods) and only
         fall back to trigram search against cities when no alias hits.
      4. When `country_code` is given, the lookup is scoped to that country —
         critical for ambiguous names ("Al Rayyan" exists in SA and Qatar;
         "Ras Al Khaimah" in UAE collides with "Ras Al Khair" in SA).
      5. Returns an empty resolution when no token confidently matches.
    """
    candidates: list[str] = []
    seen: set[str] = set()
    for cand in (hint, *(reversed((raw_location or "").split(",")))):
        if not cand:
            continue
        c = cand.strip()
        key = c.lower()
        if c and key not in seen:
            seen.add(key)
            candidates.append(c)
    for c in candidates:
        alias_target = _CITY_ALIASES.get(c.lower())
        lookup = alias_target or c
        matches = await db.geo.find_city(
            lookup,
            limit=1,
            min_similarity=0.5,
            country_code=country_code,
        )
        if matches:
            city = matches[0][0]
            return LocationResolution(
                city_id=city.id,
                region_code=city.region_code,
                country_code=city.country_code,
            )
    return LocationResolution(country_code=country_code)


def to_upsert(
    parsed: ParsedPosting,
    *,
    source_id: UUID,
    company_id: UUID | None,
    recruiter_id: UUID | None,
    location: LocationResolution | None = None,
) -> JobPostingUpsert:
    """Pure conversion — no DB calls.

    Caller is responsible for company/recruiter/city resolution and passes
    the resulting ids in. The `location` triple (city/region/country) comes
    from `resolve_city`; when only a country is known (city not seeded),
    `country_code` still mirrors through so country-level filters work.
    """
    loc = location or LocationResolution()
    # Coerce to a known country to guarantee the FK on
    # job_postings.country_code → countries(code) passes. JSON-LD
    # `addressCountry` is wildly inconsistent ("United States" gets
    # naively truncated to "un" by upstream parsers, etc.) — silently
    # fall back to the SA default rather than fail the whole upsert.
    country_code = coerce_country_code(
        loc.country_code or parsed.country_code, default="sa",
    )
    # Auto-detect Saudi-only + gender restrictions from title + description
    # when the parser didn't set them explicitly. This is a no-op when the
    # parser already populated the fields with a non-default value.
    from job_crawler_db import GenderPreference

    from .restrictions import (
        detect_experience_level,
        detect_gender_preference,
        detect_hybrid_days_per_week,
        detect_relocation_assistance,
        detect_remote_country_restriction,
        detect_saudi_only,
    )

    body = " ".join(p for p in (parsed.title, parsed.description) if p)
    saudi_only = parsed.saudi_nationals_only or detect_saudi_only(body)
    gender = parsed.gender_preference
    if gender is GenderPreference.any:
        gender = detect_gender_preference(body)

    # Experience level — extracted from title (most predictive — every
    # ATS includes a level keyword in the role's title) with a fallback
    # to the first paragraph of the description. Parser-provided values
    # win; heuristic only fills the blank.
    experience_level = parsed.experience_level or detect_experience_level(
        parsed.title, parsed.description,
    )
    # Three more parser-grade extractions. All three columns exist on
    # job_postings AND on jobs, so to_upsert fills the posting and
    # `create_from_posting` / `recompute_canonical` mirror up. Parser
    # values still win when explicitly set by the per-source parser.
    hybrid_days = (
        parsed.hybrid_days_per_week
        if parsed.hybrid_days_per_week is not None
        else detect_hybrid_days_per_week(parsed.description)
    )
    remote_country = (
        parsed.remote_country_restriction
        or detect_remote_country_restriction(parsed.description)
    )
    relocation_assistance = detect_relocation_assistance(parsed.description)

    # Salary normalisation — everything stored as SAR for consistent
    # range queries / facets / sorting in the UI. USD pegged to SAR at
    # 3.75 (the SAMA-set rate, stable since 1986). See
    # `_normalise_salary_to_sar` for the conversion rules.
    sal_min, sal_max, sal_currency = _normalise_salary_to_sar(
        parsed.salary_min, parsed.salary_max, parsed.salary_currency,
    )

    # Centralised text sanitisation — runs on every source so the
    # downstream consumer (search vectors, dedupe content_hash,
    # dashboard) never has to deal with invisible junk that leaks
    # through HTML parsing. See `_clean_text` for the full set:
    # html.unescape, strip BOM/ZWS/RTL marks, drop control chars,
    # collapse whitespace, strip leading/trailing space.
    # `_clean_title` builds on `_clean_text` plus title-specific stripping
    # of click-bait prefixes ("Hiring Now |", "Career Opportunities:"),
    # brand-trail pipe segments, and req-id paren suffixes.
    title = _clean_title(parsed.title)
    description = _clean_text(parsed.description)
    raw_company_name = _clean_company_name(parsed.raw_company_name)
    raw_location = _clean_text(parsed.raw_location)
    hiring_manager_name = _clean_text(parsed.hiring_manager_name)
    office_address = _clean_text(parsed.office_address)

    return JobPostingUpsert(
        source_id=source_id,
        source_job_external_id=parsed.source_job_external_id,
        canonical_url=parsed.canonical_url,
        title=title,
        description=description,
        description_html=parsed.description_html,
        company_id=company_id,
        raw_company_name=raw_company_name,
        posted_by_recruiter_id=recruiter_id,
        raw_poster_name=parsed.raw_poster_name,
        employment_type=parsed.employment_type,
        work_arrangement=parsed.work_arrangement,
        experience_level=experience_level,
        raw_location=raw_location,
        city_id=loc.city_id,
        region_code=loc.region_code,
        country_code=country_code,
        office_address=office_address,
        hybrid_days_per_week=hybrid_days,
        remote_country_restriction=remote_country,
        relocation_assistance=relocation_assistance,
        hiring_manager_name=hiring_manager_name,
        hiring_manager_linkedin_url=parsed.hiring_manager_linkedin_url,
        saudi_nationals_only=saudi_only,
        gender_preference=gender,
        salary_min=sal_min,
        salary_max=sal_max,
        salary_currency=sal_currency,
        salary_period=parsed.salary_period,
        posted_at=parsed.posted_at,
        source_updated_at=parsed.source_updated_at,
        expires_at=parsed.expires_at,
        raw_payload=parsed.raw_payload,
    )


async def persist_side_data(
    db: JobCrawlerDB,
    posting_id: UUID,
    *,
    channels: list[ApplicationChannelRaw],
    raw_skills: list[RawSkillRaw],
) -> None:
    """Write the per-posting children (channels + raw skills)."""
    for channel in channels:
        try:
            await db.postings.add_application_channel(
                posting_id,
                kind=channel.kind
                if isinstance(channel.kind, ApplicationChannelKind)
                else ApplicationChannelKind(channel.kind),
                value=channel.value,
                is_primary=channel.is_primary,
                raw_label=channel.raw_label,
            )
        except Exception:
            _LOG.exception("failed to persist application channel for %s", posting_id)

    for raw in raw_skills:
        skill_id: UUID | None = None
        if raw.skill_slug:
            skill = await db.skills.get_by_slug(raw.skill_slug)
            skill_id = skill.id if skill else None
        try:
            await db.postings.add_raw_skill(
                posting_id,
                raw.raw_phrase,
                skill_id=skill_id,
                confidence=raw.confidence,
            )
        except Exception:
            _LOG.exception("failed to persist raw skill for %s", posting_id)


# Convenience: per-field success accounting consumed by `core.health`.
REQUIRED_FIELDS: Final = ("title", "canonical_url", "raw_company_name")


def field_coverage(parsed: ParsedPosting) -> float:
    """Return the fraction of REQUIRED_FIELDS that are populated.

    The runner averages this across a batch to feed `field_fill_rate`.
    """
    hits = sum(1 for f in REQUIRED_FIELDS if getattr(parsed, f, None))
    return hits / len(REQUIRED_FIELDS)


# Keep the SkillRequirement import alive for downstream type usage.
_ = SkillRequirement
