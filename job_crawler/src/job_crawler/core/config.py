"""Per-source rate-limit + UA + timeout config.

Used by `core.http.HttpClient` to enforce politeness without each crawler
having to repeat the same boilerplate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateConfig:
    """Aggressive defaults — we want all the data we can get.

    Per-source crawlers dial DOWN when a host pushes back. The defaults
    here saturate any reasonable ATS/board endpoint without obviously
    crossing into abuse territory.
    """

    max_rps: float = 8.0   # token-bucket refill rate (req/sec)
    burst: int = 16        # initial bucket size — allow short bursts
    max_concurrent: int = 8  # AsyncSemaphore limit per host
    timeout_seconds: float = 30.0
    retry_attempts: int = 5
    user_agent: str | None = None  # None = rotate through USER_AGENTS


# Pool of modern desktop UAs. Rotated per request when the crawler doesn't pin
# one. Kept current as of late 2025 / early 2026; replace yearly.
USER_AGENTS: tuple[str, ...] = (
    # Chrome 130 macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Chrome 130 Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Firefox 132 Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
    # Safari 18 macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    # Edge 130 Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
)


# A polite "I'm a real bot for jobs.omarss.net" UA — preferred for sources
# where we want to be identifiable (ATS APIs, anything friendly).
IDENTIFIABLE_UA = "Mozilla/5.0 (compatible; jobs.omarss.net/0.1; +https://jobs.omarss.net)"


# Date window: the entire pipeline filters to the last 30 days.
LOOKBACK_DAYS_DEFAULT = 30
