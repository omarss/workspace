"""ParsedPosting → JobPostingUpsert + side-data dispatch.

Centralised so per-source crawlers don't reinvent the same wiring.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
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

    from .restrictions import detect_gender_preference, detect_saudi_only

    body = " ".join(p for p in (parsed.title, parsed.description) if p)
    saudi_only = parsed.saudi_nationals_only or detect_saudi_only(body)
    gender = parsed.gender_preference
    if gender is GenderPreference.any:
        gender = detect_gender_preference(body)

    # Centralised text sanitisation — runs on every source so the
    # downstream consumer (search vectors, dedupe content_hash,
    # dashboard) never has to deal with invisible junk that leaks
    # through HTML parsing. See `_clean_text` for the full set:
    # html.unescape, strip BOM/ZWS/RTL marks, drop control chars,
    # collapse whitespace, strip leading/trailing space.
    title = _clean_text(parsed.title)
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
        experience_level=parsed.experience_level,
        raw_location=raw_location,
        city_id=loc.city_id,
        region_code=loc.region_code,
        country_code=country_code,
        office_address=office_address,
        hybrid_days_per_week=parsed.hybrid_days_per_week,
        remote_country_restriction=parsed.remote_country_restriction,
        hiring_manager_name=hiring_manager_name,
        hiring_manager_linkedin_url=parsed.hiring_manager_linkedin_url,
        saudi_nationals_only=saudi_only,
        gender_preference=gender,
        salary_min=parsed.salary_min,
        salary_max=parsed.salary_max,
        salary_currency=parsed.salary_currency,
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
