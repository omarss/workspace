"""Playwright-based Google Maps scraper.

Two public methods:
    search_places(query, lat, lng) -> list[dict]
    fetch_place(place_url, reviews_limit) -> (detail_dict, list[review_dict])

The scraper uses a *persistent* Chromium profile (cookies survive across runs)
to keep Google's rate limiter calmer, and pauses for a human on CAPTCHA pages
rather than trying to solve them. Every field comes out of the DOM — nothing
talks to the Places API, and nothing deals with Outscraper. Selectors target
stable ARIA roles and `data-*` attributes where possible; Google's obfuscated
class names do get used but are isolated here for easy patching when they drift.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import dateparser
from playwright.sync_api import (
    BrowserContext,
    Locator,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PwTimeout,
)
from rich.console import Console

from .config import settings

console = Console(stderr=True)

SEARCH_URL_TMPL = "https://www.google.com/maps/search/{q}/@{lat},{lng},{zoom}z?hl={lang}&gl={region}"

# Regex helpers ---------------------------------------------------------------

# Google Maps place URLs embed a stable feature-id (CID) like:
#   /maps/place/.../data=!4m6!3m5!1s0x3e2f03...:0x8a7b...!...
# We use that as our primary key.
_CID_RE = re.compile(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", re.IGNORECASE)
# Two forms appear in /maps URLs:
#   - camera pose:  /@24.7136,46.6753,15z     (used on the place detail URL)
#   - data token:   !3d24.7136!4d46.6753      (used on feed result anchors)
_CAMERA_RE = re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+)")
_DATA_LATLNG_RE = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")
# Matches the "(1,234)" review-count marker that follows the rating on feed cards.
_REVIEW_COUNT_RE = re.compile(r"\((\d[\d,]*)\)")


# -- CAPTCHA handling ---------------------------------------------------------


class PlaywrightScraper:
    def __init__(self) -> None:
        self._pw: Playwright = sync_playwright().start()
        Path(settings.scraper_user_data_dir).mkdir(parents=True, exist_ok=True)
        self.ctx: BrowserContext = self._pw.chromium.launch_persistent_context(
            user_data_dir=settings.scraper_user_data_dir,
            headless=settings.scraper_headless,
            slow_mo=settings.scraper_slow_mo_ms,
            viewport={"width": 1440, "height": 900},
            locale=settings.language,
            timezone_id="Asia/Riyadh",
            args=["--disable-blink-features=AutomationControlled"],
        )
        # Let Google see our spoofed coordinates as "user location" in
        # addition to whatever we put in the URL viewport. Without this,
        # the "nearby to you" ranking signal still uses the real IP's
        # geolocation and we'd under-surface places physically far from
        # home base.
        self.ctx.grant_permissions(["geolocation"], origin="https://www.google.com")
        self.page: Page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.set_default_timeout(settings.scraper_page_timeout_ms)

    def close(self) -> None:
        try:
            self.ctx.close()
        finally:
            self._pw.stop()

    def __enter__(self) -> PlaywrightScraper:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # -- CAPTCHA / consent detection -----------------------------------------

    def _await_human_if_blocked(self) -> None:
        url = self.page.url
        blocked = any(s in url for s in ("/sorry/", "consent.google.com")) or (
            self.page.locator('iframe[src*="recaptcha"], iframe[title*="reCAPTCHA"]').count() > 0
        )
        if not blocked:
            return
        reason = "Google is asking for consent or CAPTCHA"
        console.print(f"\n[yellow bold]⏸  scraper paused:[/] {reason}")
        console.print("   Solve it in the Chromium window, then press [bold]Enter[/] here.\n")
        subprocess.run(
            ["notify-send", "-u", "critical", "gplaces_parser", reason],
            check=False,
        )
        with contextlib.suppress(EOFError):
            input()

    # -- places search -------------------------------------------------------

    def search_places(
        self,
        query: str,
        lat: float,
        lng: float,
        zoom: int = 15,
        hl: str | None = None,
    ) -> list[dict[str, Any]]:
        # Spoof the browser's geolocation API response to the district
        # centroid so Google sees us as physically there, not at the
        # host's ISP-resolved location.
        self.ctx.set_geolocation({"latitude": lat, "longitude": lng, "accuracy": 30})
        url = SEARCH_URL_TMPL.format(
            q=quote(query),
            lat=f"{lat:.6f}",
            lng=f"{lng:.6f}",
            zoom=zoom,
            lang=hl or settings.language,
            region=settings.region,
        )
        self.page.goto(url, wait_until="domcontentloaded")
        self._await_human_if_blocked()

        try:
            self.page.locator('div[role="feed"]').first.wait_for(timeout=20_000)
        except PwTimeout:
            # A highly specific query lands on the place page directly — not
            # relevant for our broad category searches, so treat as empty.
            return []

        self._scroll_feed()
        time.sleep(settings.scraper_delay_seconds)
        return self._extract_feed_cards()

    def _scroll_feed(self) -> None:
        feed = self.page.locator('div[role="feed"]').first
        last_count = -1
        stable = 0
        for _ in range(settings.scraper_max_scrolls):
            feed.evaluate("el => el.scrollTo(0, el.scrollHeight)")
            self.page.wait_for_timeout(settings.scraper_scroll_pause_ms)
            end_marker = self.page.locator(
                'p:has-text("وصلت إلى نهاية القائمة"), p:has-text("You\'ve reached the end of the list")'
            )
            if end_marker.count() and end_marker.first.is_visible():
                return
            count = feed.locator('a[href*="/maps/place/"]').count()
            if count == last_count:
                stable += 1
                if stable >= 3:
                    return
            else:
                stable = 0
                last_count = count

    def _extract_feed_cards(self) -> list[dict[str, Any]]:
        anchors = self.page.locator('div[role="feed"] a[href*="/maps/place/"]').all()
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        for a in anchors:
            href = a.get_attribute("href") or ""
            cid = _cid_from(href)
            if not cid or cid in seen:
                continue
            seen.add(cid)
            name = (a.get_attribute("aria-label") or "").strip()
            if not name:
                continue
            lat, lng = _latlng_from(href)
            rows.append(
                {
                    "place_id": cid,
                    "name": name,
                    "google_url": _abs(href),
                    "latitude": lat,
                    "longitude": lng,
                    **self._extract_card_extras(a),
                }
            )
        return rows

    def _extract_card_extras(self, anchor: Locator) -> dict[str, Any]:
        """Pull rating / review-count / subtitle from a card without opening
        the detail page. Every field is best-effort — if a card lacks a
        rating row (brand new place) we just return nothing for it."""
        card = anchor.locator("xpath=./..").first
        extras: dict[str, Any] = {}

        # Rating — the `role="img"` span carries the numeric count in its
        # aria-label across locales ("4.3 stars" / "4.3 نجوم" / "Rated 4.3…").
        try:
            rating_el = card.locator('span[role="img"][aria-label]').first
            if rating_el.count():
                aria = rating_el.get_attribute("aria-label", timeout=400) or ""
                extras["rating"] = _first_number(aria)
        except Exception:  # noqa: BLE001
            pass

        # Inner_text captures name + rating(N) + subtitle + hours etc. on
        # separate lines — cheap to parse.
        try:
            text = card.inner_text(timeout=400) if card.count() else ""
        except Exception:  # noqa: BLE001
            text = ""
        text = _strip_icons(text) or ""

        if text:
            m = _REVIEW_COUNT_RE.search(text)
            if m:
                extras["reviews"] = int(m.group(1).replace(",", ""))
            # Subtitle line uses "·" as separator: `Coffee shop · $$ · King Fahd Rd`
            for line in text.splitlines():
                line = line.strip()
                if "·" in line and len(line) < 240:
                    parts = [p.strip() for p in line.split("·") if p.strip()]
                    if parts:
                        extras["subtypes"] = [parts[0]]  # primary category
                        if len(parts) >= 2:
                            # Last part tends to be the address snippet.
                            extras["full_address"] = parts[-1]
                    break
        return extras

    # -- place detail + reviews ---------------------------------------------

    def fetch_place(
        self,
        place_url: str,
        reviews_limit: int,
        sort: str = "newest",
        geolocation: tuple[float, float] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if geolocation is not None:
            self.ctx.set_geolocation(
                {"latitude": geolocation[0], "longitude": geolocation[1], "accuracy": 30}
            )
        self.page.goto(place_url, wait_until="domcontentloaded")
        self._await_human_if_blocked()
        main = self.page.locator('div[role="main"]').first
        main.wait_for(timeout=20_000)
        detail = self._extract_detail(main)
        reviews = self._extract_reviews(reviews_limit=reviews_limit, sort=sort)
        return detail, reviews

    def _extract_detail(self, main: Locator) -> dict[str, Any]:
        def txt(loc: Locator) -> str | None:
            try:
                raw = loc.first.inner_text(timeout=500).strip() if loc.count() else None
            except Exception:  # noqa: BLE001
                return None
            return _strip_icons(raw)

        def attr(loc: Locator, name: str) -> str | None:
            try:
                return loc.first.get_attribute(name, timeout=500) if loc.count() else None
            except Exception:  # noqa: BLE001
                return None

        name = txt(main.locator("h1"))
        rating = _to_float(txt(main.locator('div.fontDisplayLarge, div[role="img"][aria-label*="stars"]')))
        reviews_count = _to_int(
            txt(main.locator('button[aria-label*="reviews" i], button:has-text("مراجعة"), button:has-text("تقييم")'))
        )
        category_raw = txt(main.locator('button[jsaction*="category"]'))
        address = txt(main.locator('button[data-item-id="address"]'))
        phone = txt(main.locator('button[data-item-id^="phone:"]'))
        website = attr(main.locator('a[data-item-id="authority"]'), "href")
        plus_code = txt(main.locator('button[data-item-id^="oloc"]'))
        price_level = txt(main.locator('span[aria-label*="Price" i]'))

        cid = _cid_from(self.page.url)
        lat, lng = _latlng_from(self.page.url)
        return {
            "place_id": cid,
            "name": name,
            "rating": rating,
            "reviews_count": reviews_count,
            "full_address": address,
            "phone": phone,
            "website": website,
            "plus_code": plus_code,
            "price_level": price_level,
            "subtypes": [category_raw] if category_raw else None,
            "latitude": lat,
            "longitude": lng,
            "google_url": self.page.url,
        }

    def _extract_reviews(self, reviews_limit: int, sort: str) -> list[dict[str, Any]]:
        tab = self.page.locator(
            'button[role="tab"][aria-label*="Reviews" i], '
            'button[role="tab"][aria-label*="مراجعات"], '
            'button[role="tab"]:has-text("مراجعات"), '
            'button[role="tab"]:has-text("Reviews")'
        )
        if tab.count() == 0:
            return []
        try:
            tab.first.click()
        except Exception:  # noqa: BLE001
            return []
        self.page.wait_for_timeout(1500)

        if sort in {"newest", "highest_rating", "lowest_rating"}:
            self._apply_sort(sort)

        try:
            self.page.locator("div[data-review-id]").first.wait_for(timeout=15_000)
        except PwTimeout:
            return []

        self._scroll_reviews(reviews_limit)
        # Expand truncated review bodies.
        more_btns = self.page.locator(
            'button:has-text("المزيد"), button:has-text("قراءة المزيد"), button:has-text("More")'
        )
        for i in range(min(more_btns.count(), reviews_limit * 2)):
            with contextlib.suppress(Exception):
                more_btns.nth(i).click(timeout=500)

        return [
            self._extract_review_node(n)
            for n in self.page.locator("div[data-review-id]").all()[:reviews_limit]
        ]

    def _apply_sort(self, sort: str) -> None:
        sort_btn = self.page.locator(
            'button[aria-label*="Sort" i], button[aria-label*="ترتيب"], button:has-text("Sort"), button:has-text("الأكثر صلة")'
        )
        if sort_btn.count() == 0:
            return
        try:
            sort_btn.first.click()
            self.page.wait_for_timeout(400)
        except Exception:  # noqa: BLE001
            return
        label_map = {
            "newest": re.compile("Newest|الأحدث"),
            "highest_rating": re.compile("Highest|الأعلى تقييمًا"),
            "lowest_rating": re.compile("Lowest|الأقل تقييمًا"),
        }
        pattern = label_map[sort]
        try:
            item = self.page.get_by_role("menuitemradio", name=pattern)
            if item.count() == 0:
                item = self.page.locator("div[role='menuitemradio'], div[role='menuitem']").filter(has_text=pattern)
            item.first.click(timeout=3_000)
            self.page.wait_for_timeout(1500)
        except Exception:  # noqa: BLE001
            return

    def _scroll_reviews(self, reviews_limit: int) -> None:
        last = -1
        stable = 0
        for _ in range(300):
            nodes = self.page.locator("div[data-review-id]")
            count = nodes.count()
            if count >= reviews_limit:
                return
            with contextlib.suppress(Exception):
                nodes.last.scroll_into_view_if_needed(timeout=3_000)
            self.page.wait_for_timeout(1500)
            if count == last:
                stable += 1
                if stable >= 3:
                    return
            else:
                stable = 0
                last = count

    def _extract_review_node(self, node: Locator) -> dict[str, Any]:
        rid = node.get_attribute("data-review-id") or ""

        def txt(loc: Locator) -> str | None:
            try:
                return loc.first.inner_text(timeout=800).strip() if loc.count() else None
            except Exception:  # noqa: BLE001
                return None

        def attr(loc: Locator, n: str) -> str | None:
            try:
                return loc.first.get_attribute(n, timeout=800) if loc.count() else None
            except Exception:  # noqa: BLE001
                return None

        # Author name — inner span of the name container; the visible avatar
        # button only wraps an img so its inner_text is empty. The
        # `d4r55` + `RfnDt` classes have been stable on Google Maps for
        # years; if they drift we fall back to the avatar button's
        # aria-label which is always `صورة "Author Name"`.
        author = txt(node.locator('.d4r55')) or _strip_quotes(
            attr(node.locator('button[aria-label*="صورة"], button[aria-label*="photo" i]'), "aria-label")
        )
        author_url = attr(node.locator('button[data-href*="/contrib/"]'), "data-href") or attr(
            node.locator('a[href*="/contrib/"]'), "href"
        )
        # ".RfnDt" is the "Local guide · N reviews · M photos" line.
        author_meta = txt(node.locator(".RfnDt"))
        author_reviews_count = _first_number(
            _match_before(author_meta, ["مراجعة", "review"])
        ) if author_meta else None

        # Rating — aria-label is `"4 نجوم"` (Arabic plural) or `"4 stars"`.
        # Regex for the leading number works regardless of the word.
        rating_aria = attr(node.locator('span.kvMYJc[role="img"]'), "aria-label") or attr(
            node.locator('[role="img"][aria-label]'), "aria-label"
        )
        rating = _first_number(rating_aria)

        # Relative time — `.rsqaWe` has been stable. Fallback: any sibling
        # span containing the Arabic marker "قبل" or "ago".
        when_text = txt(node.locator("span.rsqaWe")) or txt(
            node.locator('span:has-text("قبل"), span:has-text("ago")')
        )
        published_at = _parse_when(when_text)

        # Review body. `.wiI7pd` = the span. We already clicked every
        # "More" button beforehand, so the full text is present.
        body = txt(node.locator("span.wiI7pd"))

        likes = _to_int(txt(node.locator('button[aria-label*="helpful" i], button:has-text("مفيد")')))

        # Owner response — rare; classes tend to drift. Fall back to the
        # sibling of a "Response from the owner" label.
        owner_answer = txt(node.locator('div.CDe7pd, div:has-text("استجابة من المالك") + div'))

        # Photos — buttons carry the thumb in `background-image: url("...")`.
        photos: list[str] = []
        for btn in node.locator('button.Tya61d[style*="background-image"]').all():
            style = attr(btn, "style") or ""
            m = re.search(r'url\(["\']?(https?:[^"\')]+)', style)
            if m:
                photos.append(m.group(1))

        return {
            "review_id": rid,
            "author_title": author,
            "author_url": author_url,
            "author_reviews_count": author_reviews_count,
            "review_rating": int(rating) if rating is not None else None,
            "review_text": body,
            "review_timestamp": int(published_at.timestamp()) if published_at else None,
            "review_when_raw": when_text,  # keep the original relative-time string
            "review_likes": likes,
            "owner_answer": owner_answer,
            "review_photos": photos or None,
        }


# -- helpers -----------------------------------------------------------------


def _cid_from(url_or_href: str) -> str | None:
    m = _CID_RE.search(url_or_href)
    return m.group(1) if m else None


def _latlng_from(url_or_href: str) -> tuple[float | None, float | None]:
    # Prefer the data-token form (`!3d!4d`) because it's the one the
    # feed anchors carry. Fall back to `/@lat,lng` for detail URLs.
    m = _DATA_LATLNG_RE.search(url_or_href) or _CAMERA_RE.search(url_or_href)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def _abs(href: str) -> str:
    return href if href.startswith("http") else "https://www.google.com" + href


def _first_number(s: str | None) -> float | None:
    if not s:
        return None
    m = _NUM_RE.search(s.replace(",", ""))
    return float(m.group(0)) if m else None


def _to_float(s: str | None) -> float | None:
    return _first_number(s)


def _to_int(s: str | None) -> int | None:
    v = _first_number(s)
    return int(v) if v is not None else None


# Google Maps injects icon font chars from the Private Use Area (U+E000..U+F8FF)
# as inline glyphs next to addresses, phones, hours, etc. They render as tiny
# icons in the browser but arrive as garbage chars in inner_text. Strip them and
# collapse the resulting whitespace.
_PUA_RE = re.compile(r"[\ue000-\uf8ff]")
_WS_RE = re.compile(r"\s+")


def _strip_icons(s: str | None) -> str | None:
    if not s:
        return s
    return _WS_RE.sub(" ", _PUA_RE.sub("", s)).strip() or None


def _strip_quotes(s: str | None) -> str | None:
    """Extract name from Arabic aria-label like `صورة "Bsmh A"`."""
    if not s:
        return None
    m = re.search(r'"([^"]+)"', s) or re.search(r"'([^']+)'", s)
    return m.group(1) if m else s


def _match_before(text: str | None, markers: list[str]) -> str | None:
    """Return the substring of `text` immediately preceding the first
    `marker` found. Used for `"284 مراجعة"` → `"284 "`.
    """
    if not text:
        return None
    for m in markers:
        idx = text.find(m)
        if idx != -1:
            return text[:idx]
    return None


# Arabic relative-time parser — dateparser does NOT handle the "قبل X" form
# that Google Maps emits in ar locale, so we roll our own. Units cover every
# form Google surfaces (singular / dual / plural). Dates are approximate:
# "قبل شهر" gets mapped to now() - 30 days. That matches Google's own
# precision on its UI (never exact to the day past a month).
_AR_UNITS: dict[str, tuple[str, ...]] = {
    "second": ("ثانية", "ثانيتين", "ثواني", "ثوانٍ"),
    "minute": ("دقيقة", "دقيقتين", "دقائق"),
    "hour":   ("ساعة", "ساعتين", "ساعات"),
    "day":    ("يوم", "يومين", "أيام", "يوماً"),
    "week":   ("أسبوع", "أسبوعين", "أسابيع"),
    "month":  ("شهر", "شهرين", "أشهر", "شهور"),
    "year":   ("سنة", "سنتين", "سنوات", "عام", "أعوام"),
}
_AR_UNIT_SECONDS = {
    "second": 1, "minute": 60, "hour": 3600, "day": 86400,
    "week": 7 * 86400, "month": 30 * 86400, "year": 365 * 86400,
}
_AR_DUAL_IS_TWO = frozenset({
    "يومين", "شهرين", "سنتين", "أسبوعين", "ساعتين", "دقيقتين", "ثانيتين",
})
_AR_NUM_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_AR_AGO_RE = re.compile(r"قبل\s+(?:(\d+|[٠-٩]+)\s+)?(\S+)")


def _parse_when(s: Any) -> Any:
    if not s:
        return None
    s = s.strip() if isinstance(s, str) else s
    # English cases ("a month ago") — dateparser handles them fine.
    dp = dateparser.parse(s, languages=["ar", "en"])
    if dp is not None:
        return dp
    m = _AR_AGO_RE.match(s)
    if not m:
        return None
    n_str, unit_word = m.groups()
    if n_str:
        n_str = n_str.translate(_AR_NUM_MAP)
        n = int(n_str)
    elif unit_word in _AR_DUAL_IS_TWO:
        n = 2
    else:
        n = 1
    for unit, forms in _AR_UNITS.items():
        if unit_word in forms:
            from datetime import UTC, datetime, timedelta
            return datetime.now(UTC) - timedelta(seconds=n * _AR_UNIT_SECONDS[unit])
    return None
