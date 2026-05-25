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
from collections.abc import Iterable
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
    """Find the first JSON-LD JobPosting block in `html` and parse it.

    Convenience wrapper around `extract_job_postings` for detail-page
    callers that only ever expect one posting per document.
    """
    postings = extract_job_postings(html)
    return postings[0] if postings else None


def extract_job_postings(html: str | None) -> list[JobPostingLD]:
    """Find every JSON-LD JobPosting block in `html`.

    A single page can declare many: company careers pages typically embed
    an `ItemList` whose `itemListElement` array lists every open role with
    a full JobPosting `@type` each. We walk @graph / ItemList / arrays so
    nothing slips through.
    """
    if not html:
        return []
    out: list[JobPostingLD] = []
    for match in _JSONLD_BLOCK_RE.finditer(html):
        block = match.group(1).strip()
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        nodes = data if isinstance(data, list) else [data]
        flattened: list[dict[str, Any]] = []
        for node in nodes:
            if isinstance(node, dict):
                if isinstance(node.get("@graph"), list):
                    flattened.extend(n for n in node["@graph"] if isinstance(n, dict))
                else:
                    flattened.append(node)
        for node in flattened:
            for posting_node in _yield_job_postings(node):
                out.append(_parse(posting_node))
    return out


def _yield_job_postings(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Recurse a JSON-LD node yielding every JobPosting found.

    Handles three shapes seen in the wild:
      1. JobPosting directly.
      2. ItemList whose itemListElement entries each *are* JobPosting
         (or wrap one as `.item`).
      3. CollectionPage / WebPage whose hasPart / mainEntity is one of
         the above.
    """
    types = node.get("@type")
    if isinstance(types, str):
        types_set = {types}
    elif isinstance(types, list):
        types_set = {str(t) for t in types}
    else:
        types_set = set()
    if "JobPosting" in types_set:
        yield node
        return
    # ItemList of postings
    if "ItemList" in types_set or "itemListElement" in node:
        for entry in node.get("itemListElement", []) or []:
            if not isinstance(entry, dict):
                continue
            # entry may be a JobPosting itself or wrap one in `item`
            item = entry.get("item") if isinstance(entry.get("item"), dict) else entry
            if isinstance(item, dict):
                yield from _yield_job_postings(item)
    # CollectionPage / WebPage wrappers
    for key in ("hasPart", "mainEntity"):
        child = node.get(key)
        if isinstance(child, dict):
            yield from _yield_job_postings(child)
        elif isinstance(child, list):
            for sub in child:
                if isinstance(sub, dict):
                    yield from _yield_job_postings(sub)


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
    # Pre-compute the salary + location sub-dicts then explode them
    # field-by-field. `**dict` unpacking confuses mypy when the source
    # dict has a wider value type than the target dataclass fields —
    # listing the assignments keeps strict mode happy.
    salary = _salary(node.get("baseSalary"))
    loc = _location(node.get("jobLocation"))
    return JobPostingLD(
        title=_str(node.get("title")),
        description=_html_to_text(_str(node.get("description"))),
        posted_at=_iso(node.get("datePosted")),
        valid_through=_iso(node.get("validThrough")),
        employment_type=_employment(node.get("employmentType")),
        min_experience_years=_experience_years(node.get("experienceRequirements")),
        salary_min=salary.get("salary_min"),
        salary_max=salary.get("salary_max"),
        salary_currency=salary.get("salary_currency"),
        salary_period=salary.get("salary_period"),
        company_name=_company_name(node.get("hiringOrganization")),
        company_url=_company_url(node.get("hiringOrganization")),
        city=loc.get("city"),
        region=loc.get("region"),
        country=loc.get("country"),
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
    out: dict[str, str | None] = {"city": None, "region": None, "country": None}
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


def _html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    # Same double-encoding trap as Finding 11 (Greenhouse), now in the
    # JSON-LD path: Cisco/DXC/etc. embed `"description":"&lt;p&gt;..."`
    # in their JSON-LD `JobPosting` blocks. Stripping tags BEFORE
    # `html.unescape` is a no-op (the parser sees plain text), then
    # `to_upsert.html.unescape` decodes `&lt;p&gt;` back into raw `<p>`
    # in the DB. Decode first so HTMLParser can actually strip tags.
    import html as _html

    from selectolax.parser import HTMLParser

    return HTMLParser(_html.unescape(value)).text(separator="\n", strip=True)
