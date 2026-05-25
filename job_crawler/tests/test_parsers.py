"""Unit tests for per-source parsers — no DB, no network.

Covers FINDINGS:
  * 11 — Greenhouse stored descriptions full of literal `<p>` tags because
         `HTMLParser(escaped_html).text()` was a no-op when content arrived
         entity-encoded. Parser now `html.unescape()`s before stripping tags.
  * 12 — Wuzzuf rows were saved with no description / company; treat them as
         parse failures so the runner records the failure and clusters
         aren't created from empty rows. Mihnati saved a promotional card
         titled "أعلن عن وظيفتك الأولى مجاناً!" as a real job — reject those.
  * 13 — Defensive: a JSON-LD title with `&amp;` should be unescaped by
         `to_upsert` before persistence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from job_crawler.ats.greenhouse import GreenhouseCrawler
from job_crawler.boards.mihnati import MihnatiCrawler
from job_crawler.boards.wuzzuf import WuzzufCrawler
from job_crawler.core.normalise import (
    LocationResolution,
    coerce_country_code,
    to_upsert,
)
from job_crawler.core.types import Listing, ParsedPosting, RawPosting


def _raw(payload: dict[str, Any], *, url: str = "https://example.invalid/job/1") -> RawPosting:
    """Build a RawPosting fixture without going through HttpClient."""
    return RawPosting(
        listing=Listing(source_job_external_id="1", detail_url=url),
        canonical_url=url,
        payload=payload,
        fetched_at=datetime.now(UTC),
        duration_ms=0,
        http_status=200,
        bytes=0,
    )


def _greenhouse(payload_content: str) -> ParsedPosting | None:
    """Greenhouse parse with a stub job JSON."""
    # GreenhouseCrawler.__init__ requires an http client but parse() doesn't
    # touch it — pass None and ignore the type checker. The class doesn't
    # validate the http arg in __slots__-only init.
    crawler = GreenhouseCrawler.__new__(GreenhouseCrawler)
    crawler.http = None  # type: ignore[assignment]
    crawler.db = None
    job = {
        "id": 42,
        "title": "Senior Python Engineer",
        "content": payload_content,
        "company_name": "Acme",
        "location": {"name": "Riyadh, Saudi Arabia"},
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/42",
        "first_published": "2026-05-20T10:00:00Z",
        "updated_at": "2026-05-21T10:00:00Z",
    }
    return crawler.parse(_raw({"json": job, "board_slug": "acme"}))


def test_greenhouse_decodes_double_encoded_content() -> None:
    """Real Greenhouse boards return content as HTML-entity-encoded HTML.

    Before the fix, `HTMLParser("&lt;p&gt;Hi&lt;/p&gt;").text()` returned
    the literal `<p>Hi</p>` string — tags survived into the DB.
    """
    parsed = _greenhouse("&lt;p&gt;Build great software.&lt;/p&gt;&lt;p&gt;Python.&lt;/p&gt;")
    assert parsed is not None
    assert parsed.description is not None
    assert "<p>" not in parsed.description
    assert "&lt;" not in parsed.description
    assert "Build great software." in parsed.description
    assert "Python." in parsed.description
    # description_html keeps the decoded HTML so the dashboard can render it.
    assert parsed.description_html is not None
    assert "<p>Build great software.</p>" in parsed.description_html


def test_greenhouse_handles_already_unescaped_content() -> None:
    """When a Greenhouse board returns raw HTML (no double-encoding) the
    parser still strips tags correctly. Idempotent."""
    parsed = _greenhouse("<p>Build great software.</p><p>Python.</p>")
    assert parsed is not None
    assert parsed.description is not None
    assert "<p>" not in parsed.description
    assert "Build great software." in parsed.description


def test_greenhouse_html_entity_in_text_is_decoded() -> None:
    """Title-like text with `&amp;` should appear as `&` in the stripped form."""
    parsed = _greenhouse("&lt;p&gt;Sales &amp;amp; Marketing&lt;/p&gt;")
    assert parsed is not None
    assert parsed.description is not None
    assert "Sales & Marketing" in parsed.description


# ---------------------------------------------------------------------------
# Wuzzuf required-field gate (Finding 12a)
# ---------------------------------------------------------------------------
_WUZZUF_DETAIL_TEMPLATE = """
<html><body>
  <h1>{title}</h1>
  {company_block}
  <span data-test="job-location">Riyadh</span>
  {body_block}
</body></html>
"""


def _wuzzuf(html: str) -> ParsedPosting | None:
    crawler = WuzzufCrawler.__new__(WuzzufCrawler)
    crawler.http = None  # type: ignore[assignment]
    crawler.db = None
    return crawler.parse(_raw({"html": html, "url": "https://wuzzuf.net/jobs/p/Senior-1234"},
                              url="https://wuzzuf.net/jobs/p/Senior-1234"))


def test_wuzzuf_rejects_empty_description_and_company() -> None:
    """Wuzzuf detail pages that yield neither company nor body must NOT
    write a posting — Finding 12 documented 15/15 live rows missing both."""
    html = _WUZZUF_DETAIL_TEMPLATE.format(
        title="Performance Marketing Executive",
        company_block="",
        body_block="",
    )
    parsed = _wuzzuf(html)
    assert parsed is None, (
        "parser should return None when company and description are absent"
    )


def test_wuzzuf_accepts_complete_card() -> None:
    """Happy path: when company + body are present, parse succeeds."""
    html = _WUZZUF_DETAIL_TEMPLATE.format(
        title="Backend Engineer",
        company_block='<a href="/jobs/at/acme">Acme Corp</a>',
        body_block='<div data-test="job-details">We hire engineers who love Python.</div>',
    )
    parsed = _wuzzuf(html)
    assert parsed is not None
    assert parsed.title == "Backend Engineer"
    assert parsed.raw_company_name == "Acme Corp"
    assert parsed.description is not None
    assert "Python" in parsed.description


# ---------------------------------------------------------------------------
# Mihnati promo-title filter (Finding 12b)
# ---------------------------------------------------------------------------
def _mihnati(title: str, body: str = "Some real description.") -> ParsedPosting | None:
    crawler = MihnatiCrawler.__new__(MihnatiCrawler)
    crawler.http = None  # type: ignore[assignment]
    crawler.db = None
    html = f"""
    <html><body>
      <h1>{title}</h1>
      <span class="company">Acme</span>
      <span class="location">Riyadh</span>
      <div class="description">{body}</div>
    </body></html>
    """
    return crawler.parse(_raw({"html": html}, url="https://mihnati.com/jobs/1"))


def test_mihnati_rejects_promo_card_arabic() -> None:
    """Mihnati's 'post your job free' promo card was being stored as a job
    (live row `019e5e2a-d4fa-7142-afc9-0d097723b4b6`)."""
    parsed = _mihnati("أعلن عن وظيفتك الأولى مجاناً!")
    assert parsed is None


def test_mihnati_rejects_promo_card_english() -> None:
    parsed = _mihnati("Post your job for free")
    assert parsed is None


def test_mihnati_accepts_real_job() -> None:
    parsed = _mihnati("Senior Accountant")
    assert parsed is not None
    assert parsed.title == "Senior Accountant"


# ---------------------------------------------------------------------------
# Defensive: to_upsert always unescapes HTML entities in title (Finding 13)
# ---------------------------------------------------------------------------
def test_to_upsert_unescapes_entity_titles() -> None:
    """JSON-LD often leaks `&amp;` into titles; to_upsert must decode them
    before persistence so search vectors see the real glyphs."""
    parsed = ParsedPosting(
        source_job_external_id="bayt-amp-1",
        canonical_url="https://bayt.com/jobs/bayt-amp-1",
        title="Sales Manager &amp; Marketing",
        description="Plain body.",
        raw_company_name="Acme &amp; Co",
        raw_location="Riyadh",
    )
    upsert = to_upsert(
        parsed,
        source_id=UUID(int=1),
        company_id=None,
        recruiter_id=None,
        location=None,
    )
    assert upsert.title == "Sales Manager & Marketing"
    assert upsert.raw_company_name == "Acme & Co"


# ---------------------------------------------------------------------------
# coerce_country_code: defends the FK on job_postings.country_code →
# countries(code). JSON-LD `addressCountry` is wildly inconsistent —
# we've seen "United States" naively truncated to "un", bare ISO codes,
# upper/lowercase mixes, free-text city names that happen to start with
# two letters. Any unknown value must fall back to "sa".
# ---------------------------------------------------------------------------
def test_coerce_country_code_accepts_known_codes() -> None:
    for code in ("sa", "ae", "bh", "kw", "om", "qa"):
        assert coerce_country_code(code) == code
        assert coerce_country_code(code.upper()) == code


def test_coerce_country_code_rejects_unknown_codes_with_default() -> None:
    # "United States" → "un" via the legacy `.lower()[:2]` truncation.
    # That's the exact failure that took down 6+ Cisco postings in a
    # live run; this test guards the regression.
    assert coerce_country_code("United States") == "sa"
    assert coerce_country_code("us") == "sa"
    assert coerce_country_code("XX") == "sa"
    assert coerce_country_code("") == "sa"
    assert coerce_country_code(None) == "sa"


def test_coerce_country_code_respects_explicit_default() -> None:
    """Tests / non-SA crawlers can override the fallback."""
    assert coerce_country_code("United Kingdom", default="ae") == "ae"
    assert coerce_country_code("ae", default="ae") == "ae"


def test_to_upsert_coerces_bogus_country_code_to_sa() -> None:
    """End-to-end: a ParsedPosting with country_code='un' (the live bug)
    yields a JobPostingUpsert with country_code='sa' — FK-safe."""
    parsed = ParsedPosting(
        source_job_external_id="cc-cisco-1",
        canonical_url="https://careers.cisco.com/job/123",
        title="Sourcing Commodity Manager",
        description="Plain body.",
        raw_location="Various",
        country_code="un",  # the exact failure mode
    )
    upsert = to_upsert(
        parsed,
        source_id=UUID(int=2),
        company_id=None,
        recruiter_id=None,
        location=None,
    )
    assert upsert.country_code == "sa"


def test_to_upsert_keeps_seeded_country_from_location_resolution() -> None:
    """When resolve_city returns a real country code, to_upsert mirrors
    it — coercion only kicks in for unknown values."""
    parsed = ParsedPosting(
        source_job_external_id="cc-acme-1",
        canonical_url="https://careers.acme.ae/job/1",
        title="Engineer",
        description="Plain body.",
        country_code="sa",  # parsed default
    )
    upsert = to_upsert(
        parsed,
        source_id=UUID(int=3),
        company_id=None,
        recruiter_id=None,
        location=LocationResolution(country_code="ae"),
    )
    assert upsert.country_code == "ae"


# ---------------------------------------------------------------------------
# Bayt._search_url: keyword must be ASCII-safe in BOTH the request URL
# and the page-1 Referer header (HTTP/1.1 headers are latin-1).
# Live regression: Arabic queries like "مهندس" (engineer) failed on
# page > 1 because the legacy `f"keywords={query.replace(' ', '+')}"`
# left raw UTF-8 in the URL, and httpx tried to latin-1-encode it
# when setting the Referer.
# ---------------------------------------------------------------------------
def test_bayt_search_url_percent_encodes_arabic_query() -> None:
    from job_crawler.boards.bayt import BaytCrawler

    crawler = BaytCrawler.__new__(BaytCrawler)
    crawler.http = None  # type: ignore[assignment]
    crawler.db = None

    url = crawler._search_url(page=2, query="مهندس")
    # 1. URL must be latin-1 / ASCII encodable — header layer requires it.
    url.encode("latin-1")  # raises UnicodeEncodeError on regression
    # 2. Query is percent-encoded, not raw UTF-8.
    assert "مهندس" not in url
    assert "keywords=%" in url


def test_bayt_search_url_preserves_space_as_plus_for_multi_word_query() -> None:
    from job_crawler.boards.bayt import BaytCrawler

    crawler = BaytCrawler.__new__(BaytCrawler)
    crawler.http = None  # type: ignore[assignment]
    crawler.db = None

    url = crawler._search_url(page=1, query="موارد بشرية")
    url.encode("latin-1")  # latin-1 safe
    # The space-as-`+` convention Bayt uses must survive percent-encoding.
    assert "+" in url.split("keywords=", 1)[1].split("&", 1)[0]
