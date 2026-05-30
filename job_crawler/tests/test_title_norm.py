"""Unit tests for `intelligence.title_norm.normalize_title`.

Guards the May-2026 corruption regression: the bare token "de" was being
expanded to "Data Engineer", turning "Chef de Cuisine" into "Chef Data
Engineer Cuisine". Ambiguous short abbreviations now only expand when the
source token is uppercase.
"""

from __future__ import annotations

import pytest

from job_crawler.intelligence.title_norm import normalize_title


@pytest.mark.parametrize(
    "raw,expected",
    [
        # The regression: lowercase French "de" must NOT become "Data Engineer".
        ("Chef de Cuisine", "Chef De Cuisine"),
        ("Chef De Cuisine", "Chef De Cuisine"),
        ("Chef de Partie", "Chef De Partie"),
        # Lowercase English "be" is the verb, not Backend.
        ("Roles to be filled", "Roles To Be Filled"),
        # Lowercase "se"/"fe"/"ds" left alone.
        ("Maison de Mode", "Maison De Mode"),
    ],
)
def test_ambiguous_lowercase_tokens_not_expanded(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Uppercase abbreviations are genuine — they still expand.
        ("Senior DE", "Senior Data Engineer"),
        ("BE Engineer", "Backend Engineer"),
        ("DS Lead", "Data Scientist Lead"),
    ],
)
def test_uppercase_abbreviations_still_expand(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


def test_unambiguous_abbreviations_case_insensitive() -> None:
    # Multi-letter unambiguous abbreviations expand regardless of case.
    assert normalize_title("Sr SWE") == "Senior Software Engineer"
    assert normalize_title("devops engineer") == "DevOps Engineer"


def test_none_and_empty() -> None:
    assert normalize_title(None) is None
    assert normalize_title("   ") is None
