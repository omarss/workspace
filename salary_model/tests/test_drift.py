from __future__ import annotations

import numpy as np
import pandas as pd

from salary_model.monitoring.drift import (
    PSI_ALERT,
    PSI_WARN,
    compute_drift,
)


def test_no_drift_when_distributions_identical() -> None:
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"x": rng.normal(size=2000), "c": rng.choice(["a", "b", "c"], size=2000)})
    rep = compute_drift(df, df.copy())
    assert rep.max_psi < PSI_WARN
    assert all(f.severity == "ok" for f in rep.per_feature)


def test_high_drift_when_distributions_shifted() -> None:
    rng = np.random.default_rng(1)
    ref = pd.DataFrame({"x": rng.normal(loc=0.0, scale=1.0, size=2000)})
    curr = pd.DataFrame({"x": rng.normal(loc=3.0, scale=1.0, size=2000)})
    rep = compute_drift(ref, curr)
    assert rep.max_psi >= PSI_ALERT
    assert any(f.severity == "alert" for f in rep.per_feature)


def test_categorical_drift() -> None:
    ref = pd.DataFrame({"c": ["a"] * 800 + ["b"] * 200})
    curr = pd.DataFrame({"c": ["a"] * 200 + ["b"] * 800})
    rep = compute_drift(ref, curr)
    assert rep.per_feature[0].psi > 0.5


def test_report_markdown_has_table_header() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    rep = compute_drift(df, df)
    md = rep.to_markdown()
    assert "| feature | psi |" in md
    assert "max PSI" in md
