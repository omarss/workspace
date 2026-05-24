from __future__ import annotations

import pandas as pd

from salary_model.data.synthetic import default_spec, generate


def test_generator_is_deterministic() -> None:
    a = generate(default_spec(n_rows=500, seed=42))
    b = generate(default_spec(n_rows=500, seed=42))
    pd.testing.assert_frame_equal(a, b)


def test_generator_marginal_shape_is_sane() -> None:
    df = generate(default_spec(n_rows=4000, seed=11))
    assert df["base_monthly"].min() >= 1500.0
    assert df["base_monthly"].quantile(0.99) < 250_000.0
    assert df["tcc_monthly"].gt(df["base_monthly"]).mean() > 0.95


def test_riyadh_premium_observable() -> None:
    df = generate(default_spec(n_rows=8000, seed=7))
    ruh = df.loc[df["region"] == "RUH", "base_monthly"].median()
    baha = df.loc[df["region"] == "BAH", "base_monthly"].median()
    assert ruh > baha


def test_pif_lift_observable() -> None:
    df = generate(default_spec(n_rows=8000, seed=8))
    pif = df.loc[df["ownership"] == "pif_backed", "base_monthly"].median()
    pri = df.loc[df["ownership"] == "private", "base_monthly"].median()
    assert pif > pri


def test_source_label_consistent() -> None:
    df = generate(default_spec(n_rows=200, seed=1))
    assert (df["source"] == "synthetic_anchored").all()
    assert (df["confidence"] <= 0.7).all()
