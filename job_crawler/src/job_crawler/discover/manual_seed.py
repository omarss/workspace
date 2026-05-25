"""Loader for the curated SA companies CSV.

Idempotent: re-running upserts via `db.companies.resolve`. Safe to call
on every deploy.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Final

from job_crawler_db import JobCrawlerDB

_LOG: Final = logging.getLogger("job_crawler.discover.manual_seed")


@dataclass(slots=True)
class SeedResult:
    total: int
    created: int
    matched_existing: int


async def _ensure_reference(db: JobCrawlerDB) -> None:
    """Idempotently seed the minimum geo/reference data the schema FKs require.

    Safe to call on every load — every method here is an UPSERT.
    """
    # SA + GCC neighbours. GCC entries exist so a Bayt/LinkedIn posting from
    # Dubai/Doha/Manama/etc. resolves into the right country instead of being
    # mis-stored as country_code='sa'.
    for cc, en, ar, dial, curr in (
        ("sa", "Saudi Arabia",         "المملكة العربية السعودية", "+966", "SAR"),
        ("ae", "United Arab Emirates", "الإمارات العربية المتحدة", "+971", "AED"),
        ("bh", "Bahrain",              "البحرين",                  "+973", "BHD"),
        ("kw", "Kuwait",               "الكويت",                   "+965", "KWD"),
        ("om", "Oman",                 "عمان",                     "+968", "OMR"),
        ("qa", "Qatar",                "قطر",                      "+974", "QAR"),
    ):
        await db.reference.upsert_country(
            code=cc, name_en=en, name_ar=ar, dial_code=dial, currency=curr,
        )
    # Industry list — must cover every code referenced by the seed CSV.
    for code, en, ar in (
        ("tech_software", "Software", "البرمجيات"),
        ("fintech",       "Fintech",  "التقنية المالية"),
        ("ecommerce",     "E-commerce", "التجارة الإلكترونية"),
        ("oil_gas",       "Oil & Gas", "النفط والغاز"),
        ("banking",       "Banking",  "المصرفية"),
        ("telecom",       "Telecommunications", "الاتصالات"),
        ("retail",        "Retail",   "البيع بالتجزئة"),
        ("healthcare",    "Healthcare", "الرعاية الصحية"),
        ("real_estate",   "Real Estate", "العقارات"),
        ("airline",       "Airlines", "الطيران"),
        ("transport",     "Transport & Mobility", "النقل والتنقل"),
        ("logistics",     "Logistics", "الخدمات اللوجستية"),
        ("construction",  "Construction", "البناء والتشييد"),
        ("education",     "Education", "التعليم"),
        ("food_beverage", "Food & Beverage", "الأغذية والمشروبات"),
        ("insurance",     "Insurance", "التأمين"),
        ("automotive",    "Automotive", "السيارات"),
        ("investment",    "Investment", "الاستثمار"),
        ("mining",        "Mining",   "التعدين"),
        ("energy",        "Energy & Power", "الطاقة"),
        ("chemicals",     "Chemicals", "الكيماويات"),
        ("government",    "Government", "الحكومة"),
        ("media",         "Media",    "الإعلام"),
        ("entertainment", "Entertainment", "الترفيه"),
        ("hospitality",   "Hospitality & Tourism", "الضيافة والسياحة"),
        ("ngo",           "Non-profit / NGO", "غير ربحية"),
        ("sports",        "Sports",   "الرياضة"),
        ("cement",        "Cement & Building Materials", "الإسمنت ومواد البناء"),
        ("agriculture",   "Agriculture", "الزراعة"),
        ("pharma",        "Pharmaceuticals", "الأدوية"),
        ("manufacturing", "Manufacturing", "التصنيع"),
        ("conglomerate",  "Conglomerate", "مجموعة شركات"),
        ("petrochemicals","Petrochemicals", "البتروكيماويات"),
    ):
        await db.reference.upsert_industry(code=code, name_en=en, name_ar=ar)
    # Regions, grouped by country. Each country also gets a synthetic catch-all
    # region (`<cc>_other`) used by cities we know belong to the country but
    # have no specific admin region modelled yet.
    _SA_REGIONS = (
        ("riyadh",           "Riyadh",           "الرياض"),
        ("makkah",           "Makkah",           "مكة المكرمة"),
        ("eastern",          "Eastern",          "الشرقية"),
        ("madinah",          "Madinah",          "المدينة المنورة"),
        ("asir",             "Asir",             "عسير"),
        ("qassim",           "Qassim",           "القصيم"),
        ("hail",             "Hail",             "حائل"),
        ("tabuk",            "Tabuk",            "تبوك"),
        ("northern_borders", "Northern Borders", "الحدود الشمالية"),
        ("jazan",            "Jazan",            "جازان"),
        ("najran",           "Najran",           "نجران"),
        ("al_bahah",         "Al Bahah",         "الباحة"),
        ("al_jouf",          "Al Jouf",          "الجوف"),
    )
    # GCC admin regions kept coarse — one emirate / governorate per major city.
    # Each is keyed by its real first-level admin code so the composite FK
    # (country_code, region_code) on jobs/postings stays meaningful.
    _GCC_REGIONS: tuple[tuple[str, str, str, str], ...] = (
        ("ae", "abu_dhabi",      "Abu Dhabi",      "أبوظبي"),
        ("ae", "dubai",          "Dubai",          "دبي"),
        ("ae", "sharjah",        "Sharjah",        "الشارقة"),
        ("ae", "ajman",          "Ajman",          "عجمان"),
        ("ae", "ras_al_khaimah", "Ras Al Khaimah", "رأس الخيمة"),
        ("ae", "fujairah",       "Fujairah",       "الفجيرة"),
        ("ae", "umm_al_quwain",  "Umm Al Quwain",  "أم القيوين"),
        ("bh", "capital",        "Capital",        "العاصمة"),
        ("kw", "capital",        "Capital",        "العاصمة"),
        ("om", "muscat",         "Muscat",         "مسقط"),
        ("om", "dhofar",         "Dhofar",         "ظفار"),
        ("om", "al_batinah_north", "Al Batinah North", "شمال الباطنة"),
        ("qa", "doha",           "Doha",           "الدوحة"),
        ("qa", "al_rayyan",      "Al Rayyan",      "الريان"),
    )
    for code, name_en, name_ar in _SA_REGIONS:
        await db.geo.upsert_region(
            code=code, name_en=name_en, name_ar=name_ar, country_code="sa",
        )
    for cc, code, name_en, name_ar in _GCC_REGIONS:
        await db.geo.upsert_region(
            code=code, name_en=name_en, name_ar=name_ar, country_code=cc,
        )

    # Cities — grouped by (country, region). The composite FK on `cities`
    # makes it impossible to attach a UAE city under a SA region, so the
    # historical "tag GCC under SA Eastern" workaround is gone.
    _CITIES: tuple[tuple[str, str, str, str, float, float], ...] = (
        # ----- Saudi Arabia ----------------------------------------------
        ("sa", "riyadh",  "Riyadh",          "الرياض",     24.7136, 46.6753),
        ("sa", "riyadh",  "Al Kharj",        "الخرج",      24.1554, 47.3346),
        ("sa", "riyadh",  "Diriyah",         "الدرعية",    24.7376, 46.5747),
        ("sa", "riyadh",  "Al Majma'ah",     "المجمعة",    25.9006, 45.3603),
        ("sa", "makkah",  "Jeddah",          "جدة",        21.4858, 39.1925),
        ("sa", "makkah",  "Makkah",          "مكة",        21.3891, 39.8579),
        ("sa", "makkah",  "Taif",            "الطائف",     21.2703, 40.4158),
        ("sa", "makkah",  "Rabigh",          "رابغ",       22.7986, 39.0349),
        ("sa", "makkah",  "Al Jamoum",       "الجموم",     21.6225, 39.7044),
        ("sa", "eastern", "Dammam",          "الدمام",     26.4207, 50.0888),
        ("sa", "eastern", "Khobar",          "الخبر",      26.2172, 50.1971),
        ("sa", "eastern", "Dhahran",         "الظهران",    26.2361, 50.0393),
        ("sa", "eastern", "Jubail",          "الجبيل",     27.0046, 49.6586),
        ("sa", "eastern", "Hofuf (Al Hasa)", "الهفوف",     25.3795, 49.5867),
        ("sa", "eastern", "Qatif",           "القطيف",     26.5650, 50.0123),
        ("sa", "eastern", "Ras Tanura",      "رأس تنورة",  26.7126, 50.1632),
        ("sa", "eastern", "Abqaiq",          "بقيق",       25.9347, 49.6711),
        # Real SA industrial city — previously fuzz-matched to UAE's
        # "Ras Al Khaimah" because the SA row didn't exist.
        ("sa", "eastern", "Ras Al Khair",    "رأس الخير",  27.5167, 49.2333),
        ("sa", "eastern", "Khafji",          "الخفجي",     28.4317, 48.4904),
        ("sa", "madinah", "Madinah",         "المدينة",    24.5247, 39.5692),
        ("sa", "madinah", "Yanbu",           "ينبع",       24.0220, 38.0599),
        ("sa", "asir",    "Abha",            "أبها",       18.2164, 42.5053),
        ("sa", "asir",    "Khamis Mushait",  "خميس مشيط",  18.3000, 42.7333),
        ("sa", "asir",    "Bisha",           "بيشة",       20.0000, 42.6000),
        ("sa", "qassim",  "Buraydah",        "بريدة",      26.3260, 43.9750),
        ("sa", "qassim",  "Unaizah",         "عنيزة",      26.0840, 43.9942),
        ("sa", "hail",    "Hail",            "حائل",       27.5114, 41.6900),
        ("sa", "tabuk",   "Tabuk",           "تبوك",       28.3838, 36.5550),
        ("sa", "tabuk",   "NEOM",            "نيوم",       28.0000, 35.0000),
        ("sa", "tabuk",   "AlUla",           "العلا",      26.6087, 37.9229),
        ("sa", "northern_borders", "Arar",   "عرعر",       30.9758, 41.0381),
        ("sa", "jazan",   "Jazan",           "جازان",      16.8892, 42.5611),
        ("sa", "najran",  "Najran",          "نجران",      17.4924, 44.1277),
        ("sa", "al_bahah","Al Bahah",        "الباحة",     20.0129, 41.4677),
        ("sa", "al_jouf", "Sakaka",          "سكاكا",      29.9697, 40.2064),
        # ----- UAE -------------------------------------------------------
        ("ae", "dubai",          "Dubai",          "دبي",        25.2048, 55.2708),
        ("ae", "abu_dhabi",      "Abu Dhabi",      "أبوظبي",     24.4539, 54.3773),
        ("ae", "abu_dhabi",      "Al Ain",         "العين",      24.2074, 55.7447),
        ("ae", "sharjah",        "Sharjah",        "الشارقة",    25.3463, 55.4209),
        ("ae", "ajman",          "Ajman",          "عجمان",      25.4052, 55.5136),
        ("ae", "ras_al_khaimah", "Ras Al Khaimah", "رأس الخيمة", 25.7895, 55.9432),
        ("ae", "fujairah",       "Fujairah",       "الفجيرة",    25.1288, 56.3265),
        ("ae", "umm_al_quwain",  "Umm Al Quwain",  "أم القيوين", 25.5567, 55.5567),
        # ----- Bahrain ---------------------------------------------------
        ("bh", "capital",        "Manama",         "المنامة",    26.2235, 50.5876),
        ("bh", "capital",        "Riffa",          "الرفاع",     26.1300, 50.5550),
        # ----- Kuwait ----------------------------------------------------
        ("kw", "capital",        "Kuwait City",    "مدينة الكويت", 29.3759, 47.9774),
        # ----- Qatar -----------------------------------------------------
        ("qa", "doha",           "Doha",           "الدوحة",     25.2854, 51.5310),
        ("qa", "al_rayyan",      "Al Rayyan",      "الريان",     25.2919, 51.4244),
        # ----- Oman ------------------------------------------------------
        ("om", "muscat",            "Muscat",      "مسقط",       23.5880, 58.3829),
        ("om", "dhofar",            "Salalah",     "صلالة",      17.0151, 54.0924),
        ("om", "al_batinah_north",  "Sohar",       "صحار",       24.3473, 56.7468),
    )
    for cc, region_code, name_en, name_ar, lat, lon in _CITIES:
        await db.geo.upsert_city(
            country_code=cc,
            region_code=region_code,
            name_en=name_en,
            name_ar=name_ar,
            latitude=lat,
            longitude=lon,
        )


def _seed_csv_path() -> Path:
    """Locate the seed CSV — package resource first, dev fallback second."""
    try:
        return Path(str(resources.files("job_crawler.data") / "sa_companies_seed.csv"))
    except (FileNotFoundError, ModuleNotFoundError):
        return Path(__file__).resolve().parents[2] / "data" / "sa_companies_seed.csv"


def _skills_csv_path() -> Path:
    """Locate the bundled skills taxonomy CSV."""
    try:
        return Path(str(resources.files("job_crawler.data") / "skills_seed.csv"))
    except (FileNotFoundError, ModuleNotFoundError):
        return Path(__file__).resolve().parents[2] / "data" / "skills_seed.csv"


async def _ensure_skills(db: JobCrawlerDB) -> None:
    """Idempotently upsert the bundled skill taxonomy + aliases."""
    from job_crawler_db import SkillKind

    path = _skills_csv_path()
    if not path.is_file():
        _LOG.warning("skills CSV missing at %s — skipping", path)
        return
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        upserts = 0
        aliases_added = 0
        for row in reader:
            slug = (row.get("slug") or "").strip()
            name_en = (row.get("name_en") or "").strip()
            name_ar = (row.get("name_ar") or "").strip() or None
            kind_raw = (row.get("kind") or "hard").strip().lower()
            if not slug or not name_en:
                continue
            try:
                kind = SkillKind(kind_raw)
            except ValueError:
                kind = SkillKind.hard
            try:
                skill = await db.skills.create(
                    slug=slug, name_en=name_en, name_ar=name_ar, kind=kind,
                )
                upserts += 1
                for alias in (row.get("aliases") or "").split(";"):
                    alias = alias.strip()
                    if not alias:
                        continue
                    try:
                        await db.skills.add_alias(skill.id, alias)
                        aliases_added += 1
                    except Exception:
                        _LOG.exception("could not add alias %s for %s", alias, slug)
            except Exception:
                _LOG.exception("could not upsert skill %s", slug)
    _LOG.info("skills seeded: skills=%d aliases=%d", upserts, aliases_added)


def audit_seed_duplicates(csv_path: Path) -> dict[str, list[str]]:
    """Pre-scan: return {column: [duplicated_value, ...]} for website + linkedin_url.

    Finding 5 from FINDINGS.md: the curated seed CSV had several rows
    sharing an `https://www.linkedin.com/company/...` or `website` URL.
    Some are intentional aliases (subsidiaries with their own row); others
    are accidents. The loader can't tell them apart without an explicit
    `alias_of` / `parent_name` column, but it CAN flag them so they don't
    silently merge or get patched onto the wrong canonical row.
    """
    duplicates: dict[str, list[str]] = {"website": [], "linkedin_url": []}
    seen: dict[str, dict[str, int]] = {"website": {}, "linkedin_url": {}}
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = (line for line in fh if not line.lstrip().startswith("#"))
        reader = csv.DictReader(rows)
        for row in reader:
            for col in seen:
                val = (row.get(col) or "").strip().rstrip("/").lower()
                if val:
                    seen[col][val] = seen[col].get(val, 0) + 1
    for col, counts in seen.items():
        duplicates[col] = sorted(v for v, n in counts.items() if n > 1)
    return duplicates


async def load(db: JobCrawlerDB) -> SeedResult:
    """Upsert every row in the seed CSV via `db.companies.resolve`.

    Also ensures the SA country + the three biggest regions + cities exist,
    since companies.country_code has a FK to countries(code), and seeds the
    skill taxonomy so the intelligence layer has something to match against.
    """
    await _ensure_reference(db)
    await _ensure_skills(db)
    path = _seed_csv_path()
    if not path.is_file():
        raise FileNotFoundError(f"seed CSV missing at {path}")

    # Pre-flight: surface accidental duplicate identifiers BEFORE upsert.
    # Loader semantics merge on linkedin_url match (see below), so a
    # duplicated LinkedIn URL silently makes the second row patch the
    # first row's company — which is sometimes desired (alias) and
    # sometimes a typo. Log a single WARNING so the operator notices.
    dups = audit_seed_duplicates(path)
    for col, values in dups.items():
        if values:
            _LOG.warning(
                "seed CSV has %d duplicated %s value(s): %s — second row "
                "patches the first; add an alias_of column if intentional",
                len(values), col, ", ".join(values[:5]) + ("..." if len(values) > 5 else ""),
            )

    total = 0
    created = 0
    matched = 0
    with path.open(newline="", encoding="utf-8") as fh:
        # Strip `# section-header` comment lines before handing to csv —
        # makes the seed file readable but DictReader doesn't natively skip them.
        rows = (line for line in fh if not line.lstrip().startswith("#"))
        reader = csv.DictReader(rows)
        for row in reader:
            total += 1
            name_en = (row.get("name_en") or "").strip()
            name_ar = (row.get("name_ar") or "").strip() or None
            linkedin_url = (row.get("linkedin_url") or "").strip() or None
            website = (row.get("website") or "").strip() or None
            industry = (row.get("industry_code") or "").strip() or None
            if not name_en and not name_ar:
                continue

            # Was it already present?
            already = None
            if linkedin_url:
                already = await db.companies.get_by_linkedin_url(linkedin_url)
            if already:
                matched += 1
                # Backfill missing fields from the CSV even on subsequent
                # re-runs. Without this, websites added to the CSV after a
                # company row was first seeded never reach the DB.
                company = already
            else:
                company = await db.companies.resolve(
                    raw_name=name_en or name_ar,
                    linkedin_url=linkedin_url,
                )
                created += 1
            # Best-effort: fill in name_ar, website, industry if the resolved
            # row is missing them. resolve() returns the row pre-update so
            # we patch via update() when needed.
            patch: dict[str, object] = {}
            if name_ar and not company.name_ar:
                patch["name_ar"] = name_ar
            if website and not company.website:
                patch["website"] = website
            if industry and not company.industry_code:
                patch["industry_code"] = industry
            if patch:
                try:
                    await db.companies.update(company.id, **patch)
                except Exception:
                    _LOG.exception("could not patch company %s", company.id)
    _LOG.info(
        "seed loaded: total=%d created=%d matched_existing=%d",
        total,
        created,
        matched,
    )
    return SeedResult(total=total, created=created, matched_existing=matched)
