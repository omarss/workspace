"""Shared helpers for board crawlers (LinkedIn / Bayt / Wuzzuf / ...)."""

from __future__ import annotations

from ..core.base import BaseCrawler


class BoardCrawler(BaseCrawler):
    """Marker base — every board crawler inherits from this for grouping."""
