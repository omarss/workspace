"""Deterministic hashing for posting deduplication.

Two hashes are stored on every `job_postings` row:

  * `url_hash`     — sha256 of the *normalized* URL. Catches exact reposts
                     across different query-string orderings, trailing
                     slashes, fragments, and tracking params.
  * `content_hash` — sha256 of the *normalized* description body. Catches
                     copy-paste reposts even when the URL differs.

Both functions are pure, side-effect-free, and IDENTICAL across processes
so two crawler instances always compute the same bytes for the same input.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that are pure tracking noise; stripped from URLs before hashing.
_TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "msclkid",
        "mc_eid",
        "mc_cid",
        "ref",
        "ref_src",
        "ref_url",
        "trk",
        "trkCampaign",
        "src",
        "source",  # ATS-side referral param, not a real identifier
    }
)

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_url(url: str) -> str:
    """Canonicalise a URL for hashing.

    Lowercases scheme + host, strips the fragment, drops tracking query
    params, sorts the remaining params, and removes a trailing slash from
    non-root paths. Reversible enough for debugging but stable enough that
    two crawls of the same listing always agree.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    # Filter + sort query for determinism.
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in _TRACKING_PARAMS
    ]
    kept.sort()
    query = urlencode(kept, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))  # fragment dropped


def url_hash(url: str) -> bytes:
    """Return sha256(normalize_url(url)) as raw bytes — store in `bytea`."""
    return hashlib.sha256(normalize_url(url).encode("utf-8")).digest()


def normalize_text_for_hashing(text: str | None) -> str:
    """Collapse whitespace + casefold for content hashing.

    Casefold (not lower) so mixed-case Arabic-Latin titles hash the same
    even when one source uppercases.
    """
    if not text:
        return ""
    return _WHITESPACE_RUN.sub(" ", text).strip().casefold()


def content_hash(text: str | None) -> bytes | None:
    """Return sha256 of the normalised body, or None for empty input.

    Returning None (rather than the empty-string hash) means a missing
    description doesn't collide with another missing description in the
    `exact_content_hash` dedupe rule.
    """
    normalised = normalize_text_for_hashing(text)
    if not normalised:
        return None
    return hashlib.sha256(normalised.encode("utf-8")).digest()
