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
from uuid import UUID

from job_crawler.ats.greenhouse import GreenhouseCrawler
from job_crawler.boards.mihnati import MihnatiCrawler
from job_crawler.boards.wuzzuf import WuzzufCrawler
from job_crawler.core.normalise import to_upsert
from job_crawler.core.types import Listing, ParsedPosting, RawPosting


def _raw(payload: dict, *, url: str = "https://example.invalid/job/1") -> RawPosting:
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
