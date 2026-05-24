"""Wikidata SPARQL discovery — fetches SA-headquartered organisations.

Runs against the public Wikidata Query Service. Heavily rate-limited from
their side (we keep one in-flight request, polite UA). Use sparingly —
the CronJob runs this weekly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import httpx

from job_crawler_db import JobCrawlerDB

_LOG: Final = logging.getLogger("job_crawler.discover.wikidata")

_ENDPOINT: Final = "https://query.wikidata.org/sparql"

# Q851 = Saudi Arabia. P17 = country. P159 = headquarters location.
# We accept both `country = SA` and `hq located in SA city`, deduped.
_QUERY: Final = """
SELECT ?org ?orgLabel ?orgLabelAr ?website ?linkedin WHERE {
  ?org wdt:P31/wdt:P279* wd:Q43229.        # subclass of organisation
  { ?org wdt:P17 wd:Q851 . }
  UNION
  { ?org wdt:P159 ?hq . ?hq wdt:P17 wd:Q851 . }
  OPTIONAL { ?org wdt:P856 ?website . }
  OPTIONAL { ?org wdt:P4264 ?linkedin . }   # LinkedIn company id
  OPTIONAL { ?org rdfs:label ?orgLabelAr FILTER(LANG(?orgLabelAr)='ar') }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT 5000
"""

_UA: Final = "jobs.omarss.net/0.1 (https://jobs.omarss.net; omar.s.shaaban@gmail.com)"


@dataclass(slots=True)
class WikidataResult:
    fetched: int
    inserted: int
    skipped: int


async def fetch_and_load(db: JobCrawlerDB, *, max_rows: int | None = None) -> WikidataResult:
    """Run the SPARQL query and upsert each row via db.companies.resolve.

    `max_rows` caps the number of rows we ingest in one call (default: all).
    """
    fetched = 0
    inserted = 0
    skipped = 0
    try:
        async with httpx.AsyncClient(
            timeout=60.0,
            headers={"Accept": "application/sparql-results+json", "User-Agent": _UA},
        ) as client:
            resp = await client.get(_ENDPOINT, params={"query": _QUERY, "format": "json"})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        _LOG.exception("wikidata SPARQL fetch failed")
        return WikidataResult(0, 0, 0)

    rows = (data.get("results") or {}).get("bindings", []) or []
    for row in rows:
        if max_rows is not None and fetched >= max_rows:
            break
        fetched += 1
        name_en = (row.get("orgLabel") or {}).get("value", "").strip()
        name_ar = (row.get("orgLabelAr") or {}).get("value", "").strip() or None
        website = (row.get("website") or {}).get("value", "").strip() or None
        li_id = (row.get("linkedin") or {}).get("value", "").strip() or None
        linkedin_url = f"https://www.linkedin.com/company/{li_id}/" if li_id else None
        if not name_en and not name_ar:
            skipped += 1
            continue
        try:
            company = await db.companies.resolve(
                raw_name=name_en or name_ar,
                linkedin_url=linkedin_url,
            )
            patch: dict[str, object] = {}
            if name_ar and not company.name_ar:
                patch["name_ar"] = name_ar
            if website and not company.website:
                patch["website"] = website
            if patch:
                await db.companies.update(company.id, **patch)
            inserted += 1
        except Exception:
            _LOG.exception("could not upsert wikidata row %s", name_en or name_ar)
            skipped += 1
    return WikidataResult(fetched=fetched, inserted=inserted, skipped=skipped)
