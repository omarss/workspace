"""Extract Google-for-Jobs JSON-LD `JobPosting` blocks from a page.

Most modern job sites embed a `<script type="application/ld+json">` block
that conforms to `schema.org/JobPosting` (it's a soft requirement for
Google for Jobs ranking). Parsing it gives us authoritative fields
without DOM-scraping:

  * datePosted, validThrough         → posted_at, expires_at
  * baseSalary.{value, currency}     → salary_*
  * employmentType                   → employment_type
  * experienceRequirements           → min_experience_years
  * hiringOrganization.name          → company name
  * jobLocation.address              → city / region / country

A site can ship multiple JSON-LD blocks; we look for any whose `@type`
includes `JobPosting`.
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from job_crawler_db import EmploymentType, SalaryPeriod

_JSONLD_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


@dataclass(slots=True, frozen=True)
class JobPostingLD:
    """Subset of schema.org/JobPosting fields we map to ParsedPosting."""

    title: str | None = None
    description: str | None = None
    posted_at: datetime | None = None
    valid_through: datetime | None = None
    employment_type: EmploymentType | None = None
    min_experience_years: int | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: SalaryPeriod | None = None
    company_name: str | None = None
    company_url: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None


def extract_job_posting(html: str | None) -> JobPostingLD | None:
    """Find the first JSON-LD JobPosting block in `html` and parse it."""
    if not html:
        return None
    for match in _JSONLD_BLOCK_RE.finditer(html):
        block = match.group(1).strip()
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        nodes = data if isinstance(data, list) else [data]
        # Some sites wrap nodes in an @graph array.
        flattened: list[dict[str, Any]] = []
        for node in nodes:
            if isinstance(node, dict):
                if isinstance(node.get("@graph"), list):
                    flattened.extend(n for n in node["@graph"] if isinstance(n, dict))
                else:
                    flattened.append(node)
        for node in flattened:
            types = node.get("@type")
            if isinstance(types, str):
                types_set = {types}
            elif isinstance(types, list):
                types_set = {str(t) for t in types}
            else:
                continue
            if "JobPosting" not in types_set:
                continue
            return _parse(node)
    return None


# ---------------------------------------------------------------------------
# field parsers
# ---------------------------------------------------------------------------


_EMPLOYMENT_MAP: Final[dict[str, EmploymentType]] = {
    "FULL_TIME": EmploymentType.full_time,
    "PART_TIME": EmploymentType.part_time,
    "CONTRACTOR": EmploymentType.contract,
    "CONTRACT": EmploymentType.contract,
    "TEMPORARY": EmploymentType.temporary,
    "INTERN": EmploymentType.internship,
    "INTERNSHIP": EmploymentType.internship,
    "VOLUNTEER": EmploymentType.volunteer,
    "FREELANCE": EmploymentType.freelance,
    "PER_DIEM": EmploymentType.contract,
    "OTHER": None,  # type: ignore[dict-item]
}

_UNIT_MAP: Final[dict[str, SalaryPeriod]] = {
    "HOUR": SalaryPeriod.hourly,
    "DAY": SalaryPeriod.daily,
    "WEEK": SalaryPeriod.weekly,
    "MONTH": SalaryPeriod.monthly,
    "YEAR": SalaryPeriod.annual,
}


def _parse(node: dict[str, Any]) -> JobPostingLD:
    return JobPostingLD(
        title=_str(node.get("title")),
        description=_html_to_text(_str(node.get("description"))),
        posted_at=_iso(node.get("datePosted")),
        valid_through=_iso(node.get("validThrough")),
        employment_type=_employment(node.get("employmentType")),
        min_experience_years=_experience_years(node.get("experienceRequirements")),
        **_salary(node.get("baseSalary")),
        company_name=_company_name(node.get("hiringOrganization")),
        company_url=_company_url(node.get("hiringOrganization")),
        **_location(node.get("jobLocation")),
    )


def _str(value: Any) -> str | None:
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return None


def _iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        # Some sites emit yyyy-mm-dd; let fromisoformat handle that too.
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None


def _employment(value: Any) -> EmploymentType | None:
    if isinstance(value, list) and value:
        value = value[0]
    if not isinstance(value, str):
        return None
    return _EMPLOYMENT_MAP.get(value.upper().replace("-", "_"))


def _experience_years(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    months = value.get("monthsOfExperience")
    if not isinstance(months, int | float):
        return None
    return max(0, int(months) // 12)


def _salary(value: Any) -> dict[str, Any]:
    """Returns kwargs for the SalaryHit-shaped fields on JobPostingLD."""
    out: dict[str, Any] = {
        "salary_min": None, "salary_max": None,
        "salary_currency": None, "salary_period": None,
    }
    if not isinstance(value, dict):
        return out
    currency = value.get("currency") or value.get("currencyCode")
    if isinstance(currency, str) and len(currency) == 3:
        out["salary_currency"] = currency.upper()
    qv = value.get("value")
    if isinstance(qv, list) and qv:
        qv = qv[0]
    if isinstance(qv, dict):
        for key, target in (("minValue", "salary_min"),
                            ("maxValue", "salary_max"),
                            ("value", "salary_min")):
            v = qv.get(key)
            if isinstance(v, int | float | str):
                with contextlib.suppress(Exception):
                    out[target] = Decimal(str(v))
        unit = qv.get("unitText")
        if isinstance(unit, str):
            out["salary_period"] = _UNIT_MAP.get(unit.upper())
    if out["salary_max"] is None and out["salary_min"] is not None:
        out["salary_max"] = out["salary_min"]
        if out["salary_min"] == out["salary_max"]:
            out["salary_max"] = None  # match the SalaryHit convention
    # Sanity caps (USD 500-1000/month gets through; absurd raw numbers don't)
    for k in ("salary_min", "salary_max"):
        v = out[k]
        if isinstance(v, Decimal) and (v < 50 or v > 5_000_000):
            out[k] = None
    return out


def _company_name(value: Any) -> str | None:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, dict):
        return _str(value.get("name"))
    return None


def _company_url(value: Any) -> str | None:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, dict):
        return _str(value.get("sameAs") or value.get("url"))
    return None


def _location(value: Any) -> dict[str, str | None]:
    out = {"city": None, "region": None, "country": None}
    if isinstance(value, list) and value:
        value = value[0]
    if not isinstance(value, dict):
        return out
    addr = value.get("address")
    if isinstance(addr, list) and addr:
        addr = addr[0]
    if not isinstance(addr, dict):
        return out
    out["city"] = _str(addr.get("addressLocality"))
    out["region"] = _str(addr.get("addressRegion"))
    out["country"] = _str(addr.get("addressCountry"))
    return out


def _html_to_text(html: str | None) -> str | None:
    if not html:
        return None
    # Cheap tag strip — no library cost. The DOM parser is used elsewhere
    # for richer extraction; here we just want plain text.
    from selectolax.parser import HTMLParser

    return HTMLParser(html).text(separator="\n", strip=True)
