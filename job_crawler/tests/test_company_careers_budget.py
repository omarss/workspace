"""Unit tests for the `company_careers` discover-loop budget cap.

The crawler probes ~200-400 enterprise career SPAs via Playwright on
every run. A hung tab + the cumulative cost of headless Chromium means
a single run can drift past the systemd timer interval and start
overlapping itself. `_budget_seconds()` reads
`JC_COMPANY_CAREERS_BUDGET_SECONDS` to cap the loop's wall-clock cost;
the loop bails out as soon as the budget is exhausted.
"""

from __future__ import annotations

import pytest

from job_crawler.boards.company_careers import (
    _DEFAULT_BUDGET_SECONDS,
    _budget_seconds,
)


def test_budget_default_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JC_COMPANY_CAREERS_BUDGET_SECONDS", raising=False)
    assert _budget_seconds() == _DEFAULT_BUDGET_SECONDS


def test_budget_honoured_when_env_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JC_COMPANY_CAREERS_BUDGET_SECONDS", "1800")
    assert _budget_seconds() == 1800


def test_budget_falls_back_when_env_non_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero or negative budgets would unbound the loop — fall back to
    the default rather than disable the cap."""
    monkeypatch.setenv("JC_COMPANY_CAREERS_BUDGET_SECONDS", "0")
    assert _budget_seconds() == _DEFAULT_BUDGET_SECONDS
    monkeypatch.setenv("JC_COMPANY_CAREERS_BUDGET_SECONDS", "-30")
    assert _budget_seconds() == _DEFAULT_BUDGET_SECONDS


def test_budget_falls_back_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JC_COMPANY_CAREERS_BUDGET_SECONDS", "not-a-number")
    assert _budget_seconds() == _DEFAULT_BUDGET_SECONDS
