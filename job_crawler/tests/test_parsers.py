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
# Wuzzuf required-field gate (Finding 12a) — rebuilt for the
# Emotion-CSS-in-JS layout that Wuzzuf rolled out in May 2026. The
# detail page now hashes class names per-build, so the parser is
# anchored on STRUCTURE (h1, /jobs/careers/ anchors, heading-walk for
# the description body) instead of class selectors. The template below
# mirrors that real-world DOM, including the noisy inline `<style>`
# tags that surround every visible element.
# ---------------------------------------------------------------------------
_WUZZUF_DETAIL_TEMPLATE = """
<html><body>
  <style>.css-foo{{color:red;}}</style>
  <h1 class="css-gkdl1m">{title}</h1>
  <style>.css-p7pghv{{}}</style>
  {company_block}
  <strong>{company_text} - Riyadh, Saudi Arabia</strong>
  <section>
    <h2 class="css-19118j8">Job Description</h2>
    <style>.css-n7fcne{{}}</style>
    <div class="css-n7fcne">{body_block}</div>
  </section>
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
    html = """
    <html><body>
      <style>.css-x{}</style>
      <h1>Performance Marketing Executive</h1>
    </body></html>
    """
    parsed = _wuzzuf(html)
    assert parsed is None, (
        "parser should return None when company and description are absent"
    )


def test_wuzzuf_accepts_complete_card() -> None:
    """Happy path: when company + body are present, parse succeeds.
    Uses the new `/jobs/careers/<slug>` company-anchor + heading-walked
    description body. Inline `<style>` tags must be stripped before
    text extraction — otherwise selectolax leaks CSS rules into
    `description` / `raw_company_name`."""
    html = _WUZZUF_DETAIL_TEMPLATE.format(
        title="Backend Engineer",
        company_text="Acme Corp",
        company_block='<a class="css-p7pghv" href="/jobs/careers/acme-corp-12345">Acme Corp</a>',
        body_block="We hire engineers who love Python.",
    )
    parsed = _wuzzuf(html)
    assert parsed is not None
    assert parsed.title == "Backend Engineer"
    assert parsed.raw_company_name == "Acme Corp"
    assert parsed.raw_location == "Riyadh, Saudi Arabia"
    assert parsed.description is not None
    assert "Python" in parsed.description
    # No CSS-rule leakage from inline <style> tags
    assert "css-" not in (parsed.description or "")
    assert "css-" not in (parsed.raw_company_name or "")


def test_wuzzuf_skips_browse_all_jobs_anchor() -> None:
    """Detail page wraps each section with multiple /jobs/careers/<slug>
    anchors — the genuine company name, then nav anchors like
    'Browse all jobs at X' / 'تصفّح جميع الوظائف في X'. Parser must
    return the first REAL company anchor, not the nav text."""
    html = """
    <html><body>
      <h1>Sales Lead</h1>
      <a class="css-tdvcnh" href="/jobs/careers/acme-12345">Acme Holdings</a>
      <a class="css-1gj5c6y" href="/jobs/careers/acme-12345">Browse all jobs at Acme Holdings</a>
      <strong>Acme Holdings - Jeddah, Saudi Arabia</strong>
      <section>
        <h2>Job Description</h2>
        <div>Drive revenue across the Gulf region.</div>
      </section>
    </body></html>
    """
    parsed = _wuzzuf(html)
    assert parsed is not None
    assert parsed.raw_company_name == "Acme Holdings"
    assert parsed.raw_location == "Jeddah, Saudi Arabia"


def test_wuzzuf_extracts_arabic_body_after_heading() -> None:
    """The detail page is served in Arabic by default. Heading-walk
    must find `وصف الوظيفة` and lift its body even when the parent
    section also carries leftover Emotion `<style>` tags. Regression
    against the live HTML that broke the parser on 27-May-2026."""
    html = """
    <html><body>
      <h1>مندوب مبيعات</h1>
      <a class="css-p7pghv" href="/jobs/careers/shrk-145">شركة معارض ومؤتمرات</a>
      <strong>شركة معارض ومؤتمرات-الرياض, المملكة العربية السعودية</strong>
      <section>
        <h2 class="css-19118j8">وصف الوظيفة</h2>
        <style>.css-n7fcne{}</style>
        <div class="css-n7fcne">وظيفة شاغرة من مصر الى المملكة. مندوب مبيعات ذو خبرة.</div>
        <h2 class="css-19118j8">متطلبات الوظيفة</h2>
        <div>العمر من 25 الى 35.</div>
      </section>
    </body></html>
    """
    parsed = _wuzzuf(html)
    assert parsed is not None
    assert parsed.title == "مندوب مبيعات"
    assert parsed.raw_company_name == "شركة معارض ومؤتمرات"
    # Both body sections concatenated
    desc = parsed.description or ""
    assert "وظيفة شاغرة" in desc
    assert "25 الى 35" in desc
    # Location stripped of the company prefix
    assert parsed.raw_location is not None
    assert parsed.raw_location.startswith("الرياض")


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


# ---------------------------------------------------------------------------
# company_careers required-fields gate + company_name fallback.
# Live regressions from the 100-row sample:
#   - KKU detail pages stored title="   " + the SA-gov verification banner
#     as a 14k-char "description". DOM extractors picked up page chrome.
#   - DACO detail pages stored "Company Dashboard Search Jobs Post Your CV"
#     (42 chars of navbar text) as the description.
#   - Hala / Batterjee / DXC postings landed without company_id because
#     ld.company_name was None and the parser didn't read the listing's
#     extra["company_name"] hint.
# ---------------------------------------------------------------------------
def _company_careers(
    *,
    ld: dict[str, Any] | None = None,
    html: str | None = None,
    company_name: str | None = None,
) -> ParsedPosting | None:
    from job_crawler.boards.company_careers import CompanyCareersCrawler

    crawler = CompanyCareersCrawler.__new__(CompanyCareersCrawler)
    crawler.http = None  # type: ignore[assignment]
    crawler.db = None
    payload: dict[str, Any] = {}
    if ld is not None:
        payload["ld"] = ld
    if html is not None:
        payload["html"] = html
    if company_name is not None:
        payload["company_name"] = company_name
    raw = RawPosting(
        listing=Listing(
            source_job_external_id="x",
            detail_url="https://careers.example.invalid/jobs/1",
        ),
        canonical_url="https://careers.example.invalid/jobs/1",
        payload=payload,
        fetched_at=datetime.now(UTC),
        duration_ms=0,
        http_status=200,
        bytes=0,
    )
    return crawler.parse(raw)


def test_company_careers_rejects_whitespace_only_title() -> None:
    """KKU regression — JSON-LD with title='   ' + long description must
    return None instead of writing a row with whitespace title."""
    parsed = _company_careers(
        ld={"title": "   ", "description": "A" * 500},
    )
    assert parsed is None


def test_company_careers_rejects_short_description() -> None:
    """DACO regression — the parser was scraping the page navbar
    ('Company Dashboard Search Jobs Post Your CV', 42 chars) and storing
    it as the description. Anything under 100 chars is rejected."""
    parsed = _company_careers(
        ld={
            "title": "Security System Specialist",
            "description": "Company Dashboard Search Jobs Post Your CV",
        },
    )
    assert parsed is None


def test_company_careers_uses_company_name_hint_when_jsonld_missing() -> None:
    """Hala / Batterjee regression — when ld.company_name is None, fall
    back to the company_name carried in listing.extra so the runner can
    resolve company_id instead of leaving it NULL."""
    parsed = _company_careers(
        ld={
            "title": "Software Backend Engineer",
            "description": "A" * 500,
            "company_name": None,
        },
        company_name="Hala",
    )
    assert parsed is not None
    assert parsed.raw_company_name == "Hala"


def test_company_careers_jsonld_company_name_wins_over_hint() -> None:
    """When JSON-LD does surface a company name, prefer it — it's
    posting-specific (e.g. a contractor name), not the parent firm."""
    parsed = _company_careers(
        ld={
            "title": "Engineer",
            "description": "B" * 500,
            "company_name": "Acme Subsidiary",
        },
        company_name="Acme Holding",
    )
    assert parsed is not None
    assert parsed.raw_company_name == "Acme Subsidiary"


# ---------------------------------------------------------------------------
# core/jsonld._html_to_text: same double-encoding trap as Finding 11
# (Greenhouse), now in the JSON-LD path. Cisco/DXC embed
# `"description":"&lt;p&gt;..."` in their JobPosting JSON-LD blocks.
# Stripping tags BEFORE html.unescape was a no-op; to_upsert's
# html.unescape then decoded the entities back into raw HTML in the DB.
# Regression caught live with 3 Cisco postings showing `<p>...` in
# `description_en`. Fix: html.unescape() first, then strip tags.
# ---------------------------------------------------------------------------
def test_jsonld_html_to_text_decodes_double_encoded_description() -> None:
    from job_crawler.core.jsonld import _html_to_text

    decoded = _html_to_text("&lt;p&gt;Build great software.&lt;/p&gt;")
    assert decoded is not None
    assert "<p>" not in decoded
    assert "&lt;" not in decoded
    assert "Build great software." in decoded


def test_jsonld_html_to_text_handles_raw_html_too() -> None:
    """Idempotent — raw HTML still gets stripped (no regression on the
    Greenhouse / Hala-style content that's already plain HTML)."""
    from job_crawler.core.jsonld import _html_to_text

    decoded = _html_to_text("<p>Plain raw HTML.</p>")
    assert decoded == "Plain raw HTML."


def test_company_careers_extracts_dom_posted_at_when_jsonld_omits() -> None:
    """Cisco / Halliburton / Petrofac detail pages have time[datetime] in
    the DOM but no datePosted in their JSON-LD. Without DOM fallback,
    88% of company_careers postings landed without a publish date."""
    from job_crawler.boards.company_careers import _ld_from_detail_html

    html = '''<html><head>
        <script type="application/ld+json">{
            "@type":"JobPosting",
            "title":"Senior Software Engineer",
            "description":"A"
        }</script>
    </head><body>
        <time datetime="2026-05-20T09:30:00Z">May 20</time>
    </body></html>'''
    ld = _ld_from_detail_html(html)
    assert ld.posted_at is not None
    assert ld.posted_at.year == 2026 and ld.posted_at.month == 5 and ld.posted_at.day == 20


def test_company_careers_extracts_itemprop_dateposted() -> None:
    """schema.org microdata variant — itemprop='datePosted'."""
    from job_crawler.boards.company_careers import _ld_from_detail_html

    html = '''<html><body>
        <span itemprop="datePosted" content="2026-04-15T12:00:00Z">Apr 15</span>
    </body></html>'''
    ld = _ld_from_detail_html(html)
    assert ld.posted_at is not None
    assert ld.posted_at.month == 4 and ld.posted_at.day == 15


def test_company_careers_extracts_data_attribute_dateposted() -> None:
    """Greenhouse-hosted boards stash `data-posted-at` / `data-created-at`
    on job tiles — neither itemprop nor <time> works on them."""
    from job_crawler.boards.company_careers import _ld_from_detail_html

    html = '''<html><body>
        <div data-posted-at="2026-05-18T10:00:00Z">Job tile</div>
    </body></html>'''
    ld = _ld_from_detail_html(html)
    assert ld.posted_at is not None
    assert ld.posted_at.day == 18


def test_company_careers_extracts_from_css_class_text() -> None:
    """KKU-style templates put the date in a `.posted-date` span with a
    short ISO text inside, with no semantic markup."""
    from job_crawler.boards.company_careers import _ld_from_detail_html

    html = '''<html><body>
        <div class="posted-date">2026-05-12</div>
    </body></html>'''
    ld = _ld_from_detail_html(html)
    assert ld.posted_at is not None
    assert ld.posted_at.day == 12


def test_company_careers_extracts_from_iso_regex_in_body() -> None:
    """Last-resort scan: pick the most recent ISO date in the body when
    no markup is available. Cap at last 90d so footer copyrights don't
    leak through."""
    from job_crawler.boards.company_careers import _ld_from_detail_html

    today = datetime.now(UTC).date()
    recent = today.replace(day=max(1, today.day - 3))
    html = f'''<html><body>
        <p>Footer: © 2014-2026</p>
        <p>Posted recently. See {recent.isoformat()} for details.</p>
    </body></html>'''
    ld = _ld_from_detail_html(html)
    assert ld.posted_at is not None
    assert ld.posted_at.date() == recent


def test_company_careers_skips_old_footer_dates() -> None:
    """Plain '2014' in a footer copyright must NOT become the post date."""
    from job_crawler.boards.company_careers import _ld_from_detail_html

    html = '''<html><body>
        <footer>© 2014 Company. All rights reserved.</footer>
    </body></html>'''
    ld = _ld_from_detail_html(html)
    # 2014-anything is > 90 days old → rejected; no JSON-LD, no time tag.
    assert ld.posted_at is None


def test_company_careers_parses_relative_n_days_ago_english() -> None:
    from job_crawler.boards.company_careers import _ld_from_detail_html

    html = '''<html><body>
        <span>Posted 5 days ago by the HR team</span>
    </body></html>'''
    ld = _ld_from_detail_html(html)
    assert ld.posted_at is not None
    delta = datetime.now(UTC) - ld.posted_at
    # ~5 days ± a few hours
    assert 4 < delta.days <= 5


def test_company_careers_parses_relative_arabic() -> None:
    from job_crawler.boards.company_careers import _ld_from_detail_html

    html = '''<html><body>
        <span>نشر منذ 3 أيام في الرياض</span>
    </body></html>'''
    ld = _ld_from_detail_html(html)
    assert ld.posted_at is not None
    delta = datetime.now(UTC) - ld.posted_at
    assert 2 < delta.days <= 3


def test_clean_text_strips_bom_zws_rtl_marks_and_collapses_whitespace() -> None:
    """Audit on the v6 corpus found 19 descriptions with BOM/ZWS/RTL
    chars (18 Bayt + 1 cc) and a Greenhouse title with a trailing
    space. The centralised _clean_text in to_upsert covers all of it."""
    from job_crawler.core.normalise import _clean_text

    # BOM (U+FEFF)
    assert _clean_text("﻿Senior Engineer") == "Senior Engineer"
    # zero-width space (U+200B)
    assert _clean_text("Sales​Executive") == "SalesExecutive"
    # bidi LRM (U+200E)
    assert _clean_text("Software‎Engineer") == "SoftwareEngineer"
    # trailing whitespace (the Greenhouse "Contact Center Agent " case)
    assert _clean_text("Contact Center Agent ") == "Contact Center Agent"
    # whitespace-only → None (so the column ends up NULL not '')
    assert _clean_text("   ") is None
    assert _clean_text("") is None
    assert _clean_text(None) is None
    # html.unescape still runs first
    assert _clean_text("Sales &amp; Marketing") == "Sales & Marketing"
    # Inner runs of 2+ spaces collapse to one
    assert _clean_text("Senior     Engineer") == "Senior Engineer"
    # Newlines preserved (description structure matters)
    assert _clean_text("Line 1\nLine 2") == "Line 1\nLine 2"
    # Control chars (e.g. \x07 bell) stripped, but TAB/LF/CR preserved
    assert _clean_text("Title\x07with bell") == "Titlewith bell"
    assert _clean_text("Tab\there") == "Tab\there"


def test_clean_company_name_rejects_keyboard_mash() -> None:
    """Live regression: Bayt let a HR-poster typo ('Qwer0770&') through
    as raw_company_name, which companies.resolve then materialised as a
    real company row. Reject anything with a trailing junk character
    (the most distinctive marker of typos vs real names)."""
    from job_crawler.core.normalise import _clean_company_name

    # The exact live case
    assert _clean_company_name("Qwer0770&") is None
    # Other trailing-junk variants
    assert _clean_company_name("Test!") is None
    assert _clean_company_name("Foo#") is None
    assert _clean_company_name("Bar=") is None
    assert _clean_company_name("Baz@") is None
    # Real names with digits and mixed case still pass — only trailing
    # symbol-junk triggers rejection.
    assert _clean_company_name("Center3") == "Center3"
    assert _clean_company_name("3M") == "3M"
    assert _clean_company_name("G42") == "G42"
    assert _clean_company_name("B2B Solutions") == "B2B Solutions"
    assert _clean_company_name("4horizons Group") == "4horizons Group"
    # Trailing legit punctuation (period, paren, plus) still accepted.
    assert _clean_company_name("Acme Co.") == "Acme Co."
    assert _clean_company_name("Saudi Aramco (SATORP)") == "Saudi Aramco (SATORP)"
    assert _clean_company_name("Tech+") == "Tech+"
    # _clean_text still runs first (entity decode + whitespace collapse)
    assert _clean_company_name(" Acme &amp; Co. ") == "Acme & Co."
    assert _clean_company_name(None) is None
    assert _clean_company_name("") is None


def test_company_careers_drops_sa_gov_boilerplate_description() -> None:
    """KKU regression: .gov.sa pages stored a 12k-char Arabic gov-portal
    verification banner as the description. With the boilerplate guard,
    description should drop to None while title + company_id stay."""
    from job_crawler.boards.company_careers import _SA_GOV_BOILERPLATE_PREFIX

    # The parser-side gate is what we actually want to test — verify the
    # ParsedPosting comes out with description=None when JSON-LD returns
    # the SA-gov-portal verification banner as the body.
    parsed = _company_careers(
        ld={
            "title": "وظيفة في جامعة الملك خالد",
            "description": f"{_SA_GOV_BOILERPLATE_PREFIX} كيف تتحقق روابط المواقع الإلكترونية الرسمية ..." + "X" * 1000,
            "company_name": "King Khalid University",
        },
        company_name="King Khalid University",
    )
    assert parsed is not None
    assert parsed.title == "وظيفة في جامعة الملك خالد"
    assert parsed.description is None
    assert "description" in parsed.missing_fields or "description" not in parsed.parsed_fields


def test_bayt_strips_navbar_prefix_from_title() -> None:
    """Live regression: 1 Bayt title in the v6 corpus stored as
    'View More Jobs Talent Pool (Buildings Project) - HSE Manager ...'
    because Bayt's h3#job_title block occasionally grabs the adjacent
    'View More Jobs' link text. Strip the known navbar prefixes."""
    from job_crawler.boards.bayt import _strip_bayt_title_nav_prefix

    assert (
        _strip_bayt_title_nav_prefix(
            "View More Jobs Talent Pool (Buildings Project) - HSE Manager"
        )
        == "Talent Pool (Buildings Project) - HSE Manager"
    )
    # Variant — leading whitespace + different case
    assert (
        _strip_bayt_title_nav_prefix(" view more jobs Senior Engineer")
        == "Senior Engineer"
    )
    # Other prefixes
    assert _strip_bayt_title_nav_prefix("All Jobs Sales Manager") == "Sales Manager"
    assert _strip_bayt_title_nav_prefix("Back to Jobs Engineer") == "Engineer"
    # Mid-string occurrences are real text — must not strip
    assert (
        _strip_bayt_title_nav_prefix("Manager - View More Jobs Apply Department")
        == "Manager - View More Jobs Apply Department"
    )
    # Normal title untouched
    assert _strip_bayt_title_nav_prefix("Senior Backend Engineer") == "Senior Backend Engineer"
    # Don't return empty if the title IS exactly a nav prefix
    assert _strip_bayt_title_nav_prefix("View More Jobs") == "View More Jobs"


def test_to_upsert_runs_clean_text_on_all_text_fields() -> None:
    """End-to-end: every free-text field on JobPostingUpsert is sanitised."""
    parsed = ParsedPosting(
        source_job_external_id="sanity-1",
        canonical_url="https://example.invalid/x",
        title="﻿Senior Engineer ",
        description="​We build great things.\n" + "A" * 200,
        raw_company_name="Acme‎ Co",
        raw_location="Riyadh ",
        office_address="﻿PO Box 123",
        hiring_manager_name="Sarah  Smith",  # double space
    )
    up = to_upsert(
        parsed,
        source_id=UUID(int=10),
        company_id=None,
        recruiter_id=None,
        location=None,
    )
    assert up.title == "Senior Engineer"
    assert up.description is not None and not up.description.startswith("​")
    assert up.raw_company_name == "Acme Co"
    assert up.raw_location == "Riyadh"
    assert up.office_address == "PO Box 123"
    assert up.hiring_manager_name == "Sarah Smith"


def test_company_careers_parses_absolute_posted_on() -> None:
    from job_crawler.boards.company_careers import _ld_from_detail_html

    html = '''<html><body>
        <p>Posted on May 12, 2026 in Riyadh</p>
    </body></html>'''
    ld = _ld_from_detail_html(html)
    assert ld.posted_at is not None
    assert ld.posted_at.year == 2026 and ld.posted_at.month == 5 and ld.posted_at.day == 12


def test_company_careers_jsonld_dateposted_wins_over_dom() -> None:
    """When JSON-LD has datePosted, prefer it — the DOM fallback only
    kicks in when JSON-LD is silent."""
    from job_crawler.boards.company_careers import _ld_from_detail_html

    html = '''<html><head>
        <script type="application/ld+json">{
            "@type":"JobPosting",
            "title":"Engineer",
            "description":"X",
            "datePosted":"2026-05-25T00:00:00Z"
        }</script>
    </head><body>
        <time datetime="2025-01-01T00:00:00Z">old</time>
    </body></html>'''
    ld = _ld_from_detail_html(html)
    assert ld.posted_at is not None
    assert ld.posted_at.year == 2026


def test_jsonld_extract_strips_cisco_style_double_encoded_description() -> None:
    """End-to-end: a Cisco-shaped JSON-LD block in HTML yields a
    JobPostingLD with a plain-text description (the live regression
    that landed 3 rows with `<p>` in description_en)."""
    from job_crawler.core.jsonld import extract_job_postings

    cisco_html = '''<html><head><script type="application/ld+json">{
        "@type": "JobPosting",
        "title": "Senior Software Engineer",
        "description": "&lt;p&gt;We are looking for a senior engineer.&lt;/p&gt;&lt;p&gt;Required: Python.&lt;/p&gt;"
    }</script></head><body></body></html>'''
    postings = extract_job_postings(cisco_html)
    assert len(postings) == 1
    assert postings[0].description is not None
    assert "<p>" not in postings[0].description
    assert "&lt;" not in postings[0].description
    assert "senior engineer" in postings[0].description


# ---------------------------------------------------------------------------
# _clean_title — title-specific stripping of click-bait / brand trails / IDs
# ---------------------------------------------------------------------------


def test_clean_title_strips_hiring_now_prefix() -> None:
    from job_crawler.core.normalise import _clean_title
    # Use chr() so ruff doesn't flag a literal en-dash in the source.
    en_dash = chr(0x2013)
    assert (
        _clean_title(f"Hiring Now | Tendering Engineer {en_dash} MEP")
        == f"Tendering Engineer {en_dash} MEP"
    )


def test_clean_title_strips_career_opportunities_prefix() -> None:
    from job_crawler.core.normalise import _clean_title
    assert (
        _clean_title("Career Opportunities: Divisional Trade Marketing Manager")
        == "Divisional Trade Marketing Manager"
    )


def test_clean_title_takes_longest_segment_for_brand_trail() -> None:
    from job_crawler.core.normalise import _clean_title
    # Brand-trail pipes: the longest segment is the real title.
    assert (
        _clean_title("Technical & Warranty Manager | Al-Futtaim Automotive - BYD | Riyadh")
        == "Technical & Warranty Manager"
    )
    assert (
        _clean_title("Regional Aftersales Manager | Al-Futtaim Automotive - BYD | Riyadh")
        == "Regional Aftersales Manager"
    )


def test_clean_title_strips_pure_numeric_req_id() -> None:
    from job_crawler.core.normalise import _clean_title
    assert (
        _clean_title("Divisional Trade Marketing Manager (88068)")
        == "Divisional Trade Marketing Manager"
    )


def test_clean_title_strips_tamheer_req_id() -> None:
    from job_crawler.core.normalise import _clean_title
    assert _clean_title("Procurement Intern (Tamheer 24767260)") == "Procurement Intern"


def test_clean_title_keeps_signal_paren_suffixes() -> None:
    """Parens that carry signal — Saudi-only, remote, level — stay."""
    from job_crawler.core.normalise import _clean_title
    assert _clean_title("Receptionist (Female Saudi National)") == "Receptionist (Female Saudi National)"
    assert _clean_title("AI Engineer (All Levels)") == "AI Engineer (All Levels)"
    assert _clean_title("Material Planner (Saudi Nationals Preferred)") == (
        "Material Planner (Saudi Nationals Preferred)"
    )
    assert _clean_title("Senior Architectural Technical Office Engineer (BIM)") == (
        "Senior Architectural Technical Office Engineer (BIM)"
    )


def test_clean_title_handles_urgent_hiring_paren_suffix() -> None:
    from job_crawler.core.normalise import _clean_title
    assert _clean_title("Cost Estimator (Urgent!) - Saudi Nationals") == (
        "Cost Estimator - Saudi Nationals"
    )


def test_clean_title_empty_after_cleaning_returns_none() -> None:
    from job_crawler.core.normalise import _clean_title
    assert _clean_title("") is None
    assert _clean_title("   ") is None
    assert _clean_title(None) is None


def test_clean_title_idempotent() -> None:
    from job_crawler.core.normalise import _clean_title
    once = _clean_title("Hiring Now | Mechanical Engineer (88068)")
    twice = _clean_title(once)
    assert once == "Mechanical Engineer"
    assert twice == once


# ---------------------------------------------------------------------------
# _normalise_salary_to_sar
# ---------------------------------------------------------------------------


def test_normalise_salary_usd_to_sar() -> None:
    """Bayt's JSON-LD reports USD; we convert to SAR at the SAMA peg
    (3.75). Live data sample: '$500 - $1,000' should become
    'SAR 1,875 - SAR 3,750'."""
    from decimal import Decimal

    from job_crawler.core.normalise import _normalise_salary_to_sar
    smin, smax, cur = _normalise_salary_to_sar(500, 1000, "USD")
    assert smin == Decimal("1875.00")
    assert smax == Decimal("3750.00")
    assert cur == "SAR"


def test_normalise_salary_sar_passthrough() -> None:
    from decimal import Decimal

    from job_crawler.core.normalise import _normalise_salary_to_sar
    smin, smax, cur = _normalise_salary_to_sar(8000, 12000, "SAR")
    assert smin == Decimal("8000")
    assert smax == Decimal("12000")
    assert cur == "SAR"


def test_normalise_salary_none_passthrough() -> None:
    from job_crawler.core.normalise import _normalise_salary_to_sar
    smin, smax, _ = _normalise_salary_to_sar(None, None, "SAR")
    assert smin is None
    assert smax is None


def test_normalise_salary_other_gcc_pegs() -> None:
    """AED / BHD / KWD / OMR / QAR convert via static pegs."""
    from decimal import Decimal

    from job_crawler.core.normalise import _normalise_salary_to_sar
    smin_aed, _, cur = _normalise_salary_to_sar(1000, None, "AED")
    assert cur == "SAR"
    # AED rate ≈ 1.02
    assert smin_aed == Decimal("1020.00")


def test_normalise_salary_unknown_currency_passthrough() -> None:
    """A currency we don't know is left as-is — better than guessing."""
    from decimal import Decimal

    from job_crawler.core.normalise import _normalise_salary_to_sar
    smin, _smax, cur = _normalise_salary_to_sar(100, 200, "ZAR")
    assert smin == Decimal("100")
    assert cur == "ZAR"


def test_normalise_salary_single_value_min_only() -> None:
    """A USD min without a max still converts."""
    from decimal import Decimal

    from job_crawler.core.normalise import _normalise_salary_to_sar
    smin, smax, cur = _normalise_salary_to_sar(2000, None, "USD")
    assert smin == Decimal("7500.00")
    assert smax is None
    assert cur == "SAR"
