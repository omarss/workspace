"""Unit tests for the dedup content-token guard (`_same_core_role`).

These lock in the over-merge fix: trigram title similarity alone merged
distinct-but-templated roles (measured live: false merges 0.64-0.78, true
rewordings 0.68-0.92 — overlapping). The content-token guard is the
authoritative merge decision. Every FALSE case below was an observed live
over-merge that hid a real job.
"""

from __future__ import annotations

import pytest

from job_crawler.intelligence.dedup import _core_role_tokens, _same_core_role


@pytest.mark.parametrize(
    "title_a,title_b",
    [
        # Observed live over-merges — distinct roles sharing boilerplate.
        ("Service Associate - Carpenter", "Service Associate - Service Center"),
        ("Service Associate - Waiter", "Service Associate - Service Center"),
        ("Sales Executive", "Senior Sales Executive"),
        ("Expansion Sales Executive", "Pay Expansion Executive"),
        (
            "Associate Accountant - Builders Program - (Emirati National)",
            "Compliance Associate - Builders Program - (Emirati National)",
        ),
        (
            "Associate Data Analyst - Builders Program - (Emirati National)",
            "Associate Data Scientist - Builders Program - (Emirati National)",
        ),
        # Title-corruption neighbours (different culinary roles).
        ("Chef De Cuisine", "Chef De Partie"),
        # Same role wording but different city tag -> different job.
        ("Sales Executive", "Sales Executive, Tabuk"),
    ],
)
def test_distinct_roles_are_not_merged(title_a: str, title_b: str) -> None:
    assert _same_core_role(title_a, title_b) is False


@pytest.mark.parametrize(
    "title_a,title_b",
    [
        # Seniority abbreviation — same role.
        ("Senior Python Engineer", "Sr. Python Engineer"),
        # Level marker stripped — same role.
        ("Software Engineer", "Software Engineer II"),
        # Internal job code stripped + case/'and' differences — same role.
        (
            "B2B Sales Manager - Advertising And Media Production (B2B011)",
            "B2B Sales Manager - Advertising and Media Production",
        ),
        # Identical.
        ("Customer Care Advisor (Voice)", "Customer Care Advisor (Voice)"),
    ],
)
def test_true_duplicates_still_merge(title_a: str, title_b: str) -> None:
    assert _same_core_role(title_a, title_b) is True


def test_empty_or_codeonly_titles_never_match() -> None:
    # A title that reduces to nothing (only a job code / digits) must not
    # match anything — we refuse to merge on no evidence.
    assert _core_role_tokens("(B2B011)") == frozenset()
    assert _same_core_role("(B2B011)", "(X9999)") is False
    assert _same_core_role(None, None) is False
    assert _same_core_role("", "Engineer") is False


def test_core_tokens_drop_noise_keep_seniority() -> None:
    # Seniority kept (canonicalised), stopwords/levels/codes dropped.
    assert _core_role_tokens("Sr. Data Engineer II (REQ-42)") == frozenset(
        {"senior", "data", "engineer", "req"}
    )
