"""Common crawler infrastructure — every per-site crawler depends on this."""

from .base import BaseCrawler
from .config import IDENTIFIABLE_UA, LOOKBACK_DAYS_DEFAULT, USER_AGENTS, RateConfig
from .date_window import cutoff, is_within_window, lookback_days
from .health import RunStats, record_canary, record_run_outcome
from .http import FetchResult, HttpClient
from .normalise import field_coverage, persist_side_data, resolve_city, to_upsert
from .runner import CrawlerRunner, RunSummary
from .types import (
    ApplicationChannelRaw,
    Listing,
    ParsedPosting,
    RawPosting,
    RawSkillRaw,
)

__all__ = [
    "IDENTIFIABLE_UA",
    "LOOKBACK_DAYS_DEFAULT",
    "USER_AGENTS",
    "ApplicationChannelRaw",
    "BaseCrawler",
    "CrawlerRunner",
    "FetchResult",
    "HttpClient",
    "Listing",
    "ParsedPosting",
    "RateConfig",
    "RawPosting",
    "RawSkillRaw",
    "RunStats",
    "RunSummary",
    "cutoff",
    "field_coverage",
    "is_within_window",
    "lookback_days",
    "persist_side_data",
    "record_canary",
    "record_run_outcome",
    "resolve_city",
    "to_upsert",
]
