"""Pure-regex structured-field extractors for posting descriptions.

Run after the per-source parser has done its best; whatever it left
unfilled, these try to recover from the free-text body. Conservative on
purpose — false positives here propagate to the search facet, so we
prefer to leave a field NULL than to mis-fill it.

Extractors implemented:

  * salary  — `"10,000 - 15,000 SAR/month"`, `"SAR 15 000 monthly"`,
              `"between 8000 and 12000"`, `"15k - 20k"`, Arabic forms
  * experience years  — `"5+ years"`, `"3-5 years of experience"`,
                        `"خبرة 3 سنوات"`
  * education level   — bachelor / master / phd / diploma keywords
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from job_crawler_db import EducationLevel, SalaryPeriod

# ---------------------------------------------------------------------------
# Salary
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class SalaryHit:
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str
    salary_period: SalaryPeriod | None


# Currency tokens we recognise. ISO codes plus common aliases.
_CURRENCY_TOKENS: Final[dict[str, str]] = {
    "sar": "SAR", "sr": "SAR", "ر.س": "SAR", "ريال": "SAR", "ريال سعودي": "SAR",
    "aed": "AED", "dh": "AED", "د.إ": "AED", "درهم": "AED",
    "bhd": "BHD", "د.ب": "BHD",
    "kwd": "KWD", "د.ك": "KWD",
    "qar": "QAR", "ر.ق": "QAR",
    "omr": "OMR", "ر.ع": "OMR",
    "usd": "USD", "$": "USD",
    "eur": "EUR", "€": "EUR",
    "gbp": "GBP", "£": "GBP",
}

_PERIOD_TOKENS: Final[dict[str, SalaryPeriod]] = {
    "hour": SalaryPeriod.hourly, "hourly": SalaryPeriod.hourly,
    "day": SalaryPeriod.daily,   "daily": SalaryPeriod.daily,
    "week": SalaryPeriod.weekly, "weekly": SalaryPeriod.weekly,
    "month": SalaryPeriod.monthly, "monthly": SalaryPeriod.monthly,
    "shahr": SalaryPeriod.monthly, "شهر": SalaryPeriod.monthly,
    "شهري": SalaryPeriod.monthly, "شهرياً": SalaryPeriod.monthly,
    "شهريا": SalaryPeriod.monthly,
    "year": SalaryPeriod.annual, "yearly": SalaryPeriod.annual,
    "annual": SalaryPeriod.annual, "p.a": SalaryPeriod.annual,
    "سنه": SalaryPeriod.annual, "سنة": SalaryPeriod.annual,
}

# Pre-built currency alternation (longer tokens first so "sar" doesn't
# steal a "sr" match).
_CURRENCY_RE_PART: Final = "|".join(
    re.escape(t) for t in sorted(_CURRENCY_TOKENS, key=len, reverse=True)
)
# A salary number: 10,000 / 10000 / 10k / 1.5k / 15 000.
# The k/m multiplier must attach DIRECTLY to the digits (no whitespace),
# otherwise we'd happily eat the leading 'm' of "monthly" / "month".
_NUMBER_RE_PART: Final = r"(?:\d{1,3}(?:[,\s]\d{3})+|\d+(?:\.\d+)?)(?:[kKM])?"

# Range form: "10,000 - 15,000 SAR monthly" or "SAR 10000 - 15000 / month"
_RANGE_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?:({_CURRENCY_RE_PART})\s*)?"
    rf"({_NUMBER_RE_PART})\s*(?:-|–|to|—|إلى|الى)\s*({_NUMBER_RE_PART})"  # noqa: RUF001
    rf"\s*(?:({_CURRENCY_RE_PART})\s*)?"
    rf"(?:[/\s]*(?:per\s+)?([a-zA-Zا-ي.]+))?",  # noqa: RUF001
    re.IGNORECASE,
)
# Single-value form (annual or per-month) we still want to capture, e.g.
# "Salary: 15,000 SAR / month" or "12k monthly".
_SINGLE_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?:salary|compensation|pay|الراتب)\s*[:\-]?\s*"
    rf"(?:({_CURRENCY_RE_PART})\s*)?"
    rf"({_NUMBER_RE_PART})"
    rf"\s*(?:({_CURRENCY_RE_PART})\s*)?"
    rf"(?:[/\s]*(?:per\s+)?([a-zA-Zا-ي.]+))?",  # noqa: RUF001
    re.IGNORECASE,
)


def _to_decimal(num: str) -> Decimal | None:
    s = num.replace(",", "").replace(" ", "").strip().lower()
    mult = Decimal("1")
    if s.endswith("k"):
        mult = Decimal("1000")
        s = s[:-1]
    elif s.endswith("m"):
        mult = Decimal("1000000")
        s = s[:-1]
    try:
        return Decimal(s) * mult
    except Exception:
        return None


def _norm_currency(token: str | None) -> str | None:
    if not token:
        return None
    return _CURRENCY_TOKENS.get(token.strip().lower())


def _norm_period(token: str | None) -> SalaryPeriod | None:
    if not token:
        return None
    head = token.strip().lower().rstrip("s.")
    return _PERIOD_TOKENS.get(head)


def extract_salary(
    text: str | None,
    *,
    default_currency: str = "SAR",
) -> SalaryHit | None:
    """Return a SalaryHit when the text contains a recognisable salary.

    Conservative: requires either a currency token OR an explicit
    period token in the same neighbourhood. Plain `"10000"` mentions are
    ignored to avoid years / IDs / phone-number fragments.
    """
    if not text:
        return None
    candidates: list[tuple[Decimal, Decimal, str, SalaryPeriod | None]] = []

    for m in _RANGE_RE.finditer(text):
        cur1, n1, n2, cur2, period = m.groups()
        a = _to_decimal(n1)
        b = _to_decimal(n2)
        currency = _norm_currency(cur1) or _norm_currency(cur2)
        per = _norm_period(period)
        if a is None or b is None:
            continue
        if currency is None and per is None:
            continue  # not enough context to be sure it's a salary
        if a > b:
            a, b = b, a
        candidates.append((a, b, currency or default_currency, per))

    if not candidates:
        for m in _SINGLE_RE.finditer(text):
            cur1, n1, cur2, period = m.groups()
            n = _to_decimal(n1)
            currency = _norm_currency(cur1) or _norm_currency(cur2)
            per = _norm_period(period)
            if n is None:
                continue
            if currency is None and per is None:
                continue
            candidates.append((n, n, currency or default_currency, per))

    if not candidates:
        return None
    # Take the first credible candidate; range/single ordering above
    # already prefers ranges over singles.
    lo, hi, ccy, period = candidates[0]
    # Sanity-check: drop laughable values (under 100 / over 5,000,000).
    if lo < 100 or hi > 5_000_000:
        return None
    return SalaryHit(
        salary_min=lo,
        salary_max=hi if hi != lo else None,
        salary_currency=ccy,
        salary_period=period,
    )


# ---------------------------------------------------------------------------
# Experience
# ---------------------------------------------------------------------------


_EXP_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:"
    r"(?P<min>\d{1,2})\s*(?:\+|plus|to|-|–|—|إلى|الى)?\s*"  # noqa: RUF001
    r"(?:(?P<max>\d{1,2})\s*)?"
    r"(?:years?|yrs?|سنه|سنة|سنوات)\s*(?:of\s+)?(?:experience|exp|خبرة)?"
    r")\b",
    re.IGNORECASE,
)


def extract_experience_years(text: str | None) -> tuple[int | None, int | None]:
    """Return (min_years, max_years) extracted from the text, or (None, None)."""
    if not text:
        return (None, None)
    m = _EXP_RE.search(text)
    if not m:
        return (None, None)
    a_raw = m.group("min")
    b_raw = m.group("max")
    a = int(a_raw) if a_raw else None
    b = int(b_raw) if b_raw else None
    if a is not None and b is not None and a > b:
        a, b = b, a
    # Cap at 50 — guard against random numbers ("for 100 years…").
    if a is not None and a > 50:
        return (None, None)
    return (a, b)


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------

_EDU_KEYWORDS: Final[tuple[tuple[EducationLevel, tuple[str, ...]], ...]] = (
    (EducationLevel.phd, ("phd", "ph.d", "doctorate", "doctoral", "دكتوراه")),
    (EducationLevel.master, ("master", "msc", "m.sc", "mba", "m.a", "ماجستير")),
    (EducationLevel.bachelor, ("bachelor", "bsc", "b.sc", "b.a", "b.eng", "bs ",
                                 "ba ", "بكالوريوس")),
    (EducationLevel.diploma, ("diploma", "associate degree", "دبلوم")),
    (EducationLevel.high_school, ("high school", "secondary school", "ثانوية")),
)


def extract_education_level(text: str | None) -> EducationLevel | None:
    """Pick the **highest** education level mentioned in the text."""
    if not text:
        return None
    lower = text.lower()
    for level, keywords in _EDU_KEYWORDS:   # ordered phd → high_school
        if any(k in lower for k in keywords):
            return level
    return None
