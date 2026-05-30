"""Wuzzuf (wuzzuf.net) crawler.

Wuzzuf's public search page renders server-side. URL pattern:

    https://wuzzuf.net/search/jobs/?filters%5Bcountry%5D%5B0%5D=Saudi+Arabia
                                  &filters%5Bdate_post%5D%5B0%5D=last_30_days
                                  &start={page * page_size}

Each `<div class="css-1gatmva">` (or `.job-listing-card`) card carries the
title + detail URL. The per-job page renders the description.

Configured via JC_WUZZUF_QUERY (free-text keyword) and JC_WUZZUF_MAX_PAGES.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Final
from urllib.parse import urlencode, urljoin

from selectolax.parser import HTMLParser

from job_crawler_db import (
    ApplicationChannelKind,
    EmploymentType,
    SourceKind,
    WorkArrangement,
)

from ..core.base import BaseCrawler
from ..core.config import IDENTIFIABLE_UA, RateConfig
from ..core.types import (
    ApplicationChannelRaw,
    Listing,
    ParsedPosting,
    RawPosting,
)
from ._base import BoardCrawler

_LOG: Final = logging.getLogger("job_crawler.wuzzuf")


class WuzzufCrawler(BoardCrawler):
    source_slug: ClassVar[str] = "wuzzuf"
    source_display_name: ClassVar[str] = "Wuzzuf"
    source_kind: ClassVar[SourceKind] = SourceKind.regional_board
    source_base_url: ClassVar[str] = "https://wuzzuf.net"
    source_trust_weight: ClassVar[float] = 0.55
    rate: ClassVar[RateConfig] = RateConfig(max_rps=3.0, burst=6, max_concurrent=3, timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA)
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://wuzzuf.net/search/jobs/?filters%5Bcountry%5D%5B0%5D=Saudi+Arabia",
    )

    PAGE_SIZE: ClassVar[int] = 15  # Wuzzuf default

    # Wuzzuf is built with Emotion CSS-in-JS — every element gets a
    # hashed `css-XXXXXXX` class plus an inline `<style>` tag that
    # carries the rule body. We rely on STRUCTURAL signals (tag name,
    # href pattern, heading text) rather than the volatile class names.
    #
    # Selectors kept here are deliberately minimal:
    #   * `card_link`     — listing-page anchor pattern (still stable).
    #   * `detail_title`  — `<h1>` is the role name. Always present.
    #   * `detail_company`— `/jobs/careers/<slug>` is the canonical
    #                       company-page URL. The first anchor with
    #                       real (non-CSS-rule) text is the company.
    #   * `apply_link`    — `/apply/` is the click-through anchor.
    #
    # Description body is extracted by walking siblings after the
    # localised "وصف الوظيفة" / "Job Description" heading
    # (`_extract_section_after`) rather than via a hashed class.
    PARSE_SELECTORS: ClassVar[dict[str, str]] = {
        "card_link":     "a[href*='/jobs/p/'], a[href*='/jobs/']",
        "detail_title":  "h1",
        "detail_company": "a[href*='/jobs/careers/']",
        "apply_link":    "a[href*='/apply/']",
    }
    _ID_FROM_URL_RE: ClassVar[re.Pattern[str]] = re.compile(r"/jobs/p/([^/?#]+)")

    # Heading labels used to find the description / requirements
    # sections. Wuzzuf serves detail pages in Arabic by default but
    # the listing-search filter URL is locale-agnostic, so both labels
    # need to match for resilience.
    _DESC_HEADINGS: ClassVar[tuple[str, ...]] = (
        "وصف الوظيفة", "Job Description",
    )
    _REQS_HEADINGS: ClassVar[tuple[str, ...]] = (
        "متطلبات الوظيفة", "Job Requirements",
    )

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        max_pages = int(os.environ.get("JC_WUZZUF_MAX_PAGES", "40"))
        query = os.environ.get("JC_WUZZUF_QUERY", "").strip()

        seen: set[str] = set()
        for page in range(max_pages):
            url = self._search_url(page=page, query=query)
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("wuzzuf page %d fetch failed: %s", page, exc)
                break
            tree = HTMLParser(result.text)
            anchors = tree.css(self.PARSE_SELECTORS["card_link"])
            if not anchors:
                _LOG.info("wuzzuf: no cards on page %d", page)
                break
            yielded_this_page = 0
            for a in anchors:
                href = a.attributes.get("href") or ""
                m = self._ID_FROM_URL_RE.search(href)
                if not m:
                    continue
                external_id = m.group(1)
                if external_id in seen:
                    continue
                seen.add(external_id)
                yielded_this_page += 1
                yield Listing(
                    source_job_external_id=external_id,
                    detail_url=urljoin(self.source_base_url, href),
                )
            if yielded_this_page == 0:
                break

    def _search_url(self, *, page: int, query: str) -> str:
        # `urlencode` accepts heterogeneous values (str | int) — declare
        # the dict as such so the `params["start"] = int` below
        # typechecks. Defaults to str-only otherwise.
        params: dict[str, str | int] = {
            "filters[country][0]": "Saudi Arabia",
            "filters[date_post][0]": "last_30_days",
        }
        if query:
            params["q"] = query
        if page > 0:
            params["start"] = page * self.PAGE_SIZE
        return f"{self.source_base_url}/search/jobs/?{urlencode(params)}"

    @staticmethod
    def _extract_company(tree: HTMLParser) -> str | None:
        """Pick the first `/jobs/careers/<slug>` anchor whose visible
        text is a real company name (not leftover CSS rule text or a
        nav link like "Browse all jobs at X")."""
        for a in tree.css("a[href*='/jobs/careers/']"):
            text = (a.text(strip=True) or "").strip()
            if not text:
                continue
            if text.startswith(".css-"):
                continue  # residual CSS rule slipped past the style strip
            if len(text) > 100:
                continue  # nav link with embedded helper text
            if any(p in text for p in ("جميع الوظائف", "تصفّح", "All jobs", "Browse")):
                continue
            return text
        return None

    @staticmethod
    def _extract_location(tree: HTMLParser) -> str | None:
        """The detail page shows the role's location inside a `<strong>`
        in the shape `Company-City, Country` (Arabic) or
        `Company - City, Country` (English). We slice off the company
        prefix and return the city + country part."""
        country_markers = (
            "Saudi Arabia",
            "المملكة العربية السعودية",
        )
        for strong in tree.css("strong"):
            text = (strong.text(strip=True) or "").strip()
            if not text or text.startswith(".css-"):
                continue
            if not any(m in text for m in country_markers):
                continue
            # Drop the company prefix on the left of the first hyphen
            # (Wuzzuf joins them with a bare `-` in both languages).
            if "-" in text:
                _company, _, tail = text.partition("-")
                tail = tail.strip()
                if tail:
                    return tail
            return text
        return None

    def _extract_description(self, tree: HTMLParser) -> str | None:
        """Return the description body by walking siblings after the
        "وصف الوظيفة" / "Job Description" heading until the next
        heading (or end-of-section). Concatenates the requirements
        section when present — both blocks together give the indexer
        enough text to dedupe and classify on."""
        chunks: list[str] = []
        for headings in (self._DESC_HEADINGS, self._REQS_HEADINGS):
            section = _walk_after_heading(tree, headings)
            if section:
                chunks.append(section)
        if not chunks:
            return None
        joined = "\n\n".join(chunks).strip()
        return joined or None

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        html = raw.payload.get("html")
        if not isinstance(html, str):
            return None
        tree = HTMLParser(html)
        # Wuzzuf injects an inline <style> next to virtually every
        # rendered element (Emotion CSS-in-JS), which pollutes any
        # `.text()` call with raw CSS rules. Strip those before parsing
        # so all downstream text extraction sees the visible content
        # only. `noscript` is dropped for the same reason.
        tree.strip_tags(["style", "script", "noscript"])

        title_node = tree.css_first(self.PARSE_SELECTORS["detail_title"])
        if title_node is None:
            return None
        title = title_node.text(strip=True)

        raw_company_name = self._extract_company(tree)
        raw_location = self._extract_location(tree)
        description = self._extract_description(tree)
        description_html: str | None = None  # body element is no longer
        # a single addressable block; HTML rendition would require
        # ad-hoc reassembly that buys nothing for downstream consumers.

        apply_node = tree.css_first(self.PARSE_SELECTORS["apply_link"])

        # Finding 12: Wuzzuf detail-page selectors drift more than the
        # listing layer — when neither the company nor the body matched, we
        # were saving title-only rows that the search/dedupe pipeline can't
        # use. Treat that case as a parse failure so the runner records it
        # in crawl_fetches.outcome='error' and the cluster isn't created.
        if not raw_company_name and not description:
            _LOG.info(
                "wuzzuf: dropping title-only card (no company + no body): %s",
                raw.canonical_url,
            )
            return None

        channels: list[ApplicationChannelRaw] = []
        if apply_node is not None:
            href = apply_node.attributes.get("href") or ""
            channels.append(ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=urljoin(self.source_base_url, href) if href else raw.canonical_url,
                is_primary=True,
                raw_label=apply_node.text(strip=True) or "Apply on Wuzzuf",
            ))

        posted_at = _extract_posted_at(html)

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("raw_company_name", raw_company_name),
            ("raw_location", raw_location),
            ("description", description),
        ):
            (parsed_fields if value else missing_fields).add(name)

        external_id = raw.listing.source_job_external_id
        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=posted_at,
            description=description,
            description_html=description_html,
            raw_company_name=raw_company_name,
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location),
            employment_type=EmploymentType.full_time,
            work_arrangement=_arrangement(raw_location, description),
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "wuzzuf", "html_bytes": len(html)},
        )
# ---- helpers --------------------------------------------------------------
def _walk_after_heading(
    tree: HTMLParser, heading_labels: tuple[str, ...],
) -> str | None:
    """Find an `<h2>` whose text matches one of `heading_labels`, then
    collect text from its next siblings until another heading or the
    end of the parent block.

    Wuzzuf's detail page wraps each section in a `<section>` with the
    `<h2>` as the first child and the body as the following siblings.
    Walking `node.next` until the next `h2`/`h3` is enough to lift the
    body out without depending on the volatile `css-XXXXXXX` class
    names assigned by Emotion CSS-in-JS.
    """
    target = {label.casefold() for label in heading_labels}
    for h in tree.css("h2"):
        text = (h.text(strip=True) or "").strip()
        if not text or text.casefold() not in target:
            continue
        chunks: list[str] = []
        sib = h.next
        while sib is not None:
            if sib.tag in ("h2", "h3"):
                break
            piece = (sib.text(separator="\n", strip=True) or "").strip()
            if piece:
                chunks.append(piece)
            sib = sib.next
        if chunks:
            return "\n".join(chunks).strip() or None
    return None


_REL_TIME_RE = re.compile(
    r"(\d+)\s*(minute|hour|day|week|month)s?\s*ago", re.IGNORECASE,
)


def _extract_posted_at(html: str) -> datetime | None:
    m = _REL_TIME_RE.search(html)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    delta = {
        "minute": timedelta(minutes=n),
        "hour":   timedelta(hours=n),
        "day":    timedelta(days=n),
        "week":   timedelta(weeks=n),
        "month":  timedelta(days=n * 30),
    }.get(unit, timedelta())
    return datetime.now(UTC) - delta


def _city_hint(raw_location: str | None) -> str | None:
    if not raw_location:
        return None
    return raw_location.split(",")[0].strip() or None


def _arrangement(loc: str | None, desc: str | None) -> WorkArrangement | None:
    blob = " ".join(x for x in (loc, desc) if x).lower()
    if not blob:
        return None
    if "remote" in blob:
        return WorkArrangement.remote
    if "hybrid" in blob:
        return WorkArrangement.hybrid
    return WorkArrangement.onsite


_ = BaseCrawler
