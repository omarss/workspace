"""Unit tests for the URL + content hashing helpers."""

from __future__ import annotations

from job_crawler_db import content_hash, normalize_url, url_hash


def test_url_strips_tracking_params() -> None:
    assert (
        normalize_url(
            "https://Linkedin.com/Jobs/12345?utm_source=newsletter&utm_campaign=spring",
        )
        == "https://linkedin.com/Jobs/12345"
    )


def test_url_sorts_remaining_params() -> None:
    assert normalize_url("https://acme.sa/careers?b=2&a=1") == normalize_url(
        "https://acme.sa/careers?a=1&b=2"
    )


def test_url_lowercases_scheme_and_host() -> None:
    assert normalize_url("HTTPS://Bayt.COM/x") == "https://bayt.com/x"


def test_url_drops_fragment_and_trailing_slash() -> None:
    assert normalize_url("https://x.com/a/b/#contact") == normalize_url("https://x.com/a/b")


def test_url_hash_is_deterministic_and_32_bytes() -> None:
    h = url_hash("https://acme.sa/jobs/1")
    assert isinstance(h, bytes)
    assert len(h) == 32
    assert h == url_hash("https://ACME.sa/jobs/1?utm_source=x")  # same after norm


def test_content_hash_collapses_whitespace_and_casefolds() -> None:
    assert content_hash("Hello\nWorld") == content_hash("hello   world")


def test_content_hash_returns_none_for_empty_or_whitespace() -> None:
    assert content_hash("") is None
    assert content_hash(None) is None
    assert content_hash("   \n\t  ") is None
