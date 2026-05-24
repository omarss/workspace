from __future__ import annotations

import numpy as np

from salary_model.data.synthetic import default_spec, generate
from salary_model.features.build import (
    SENSITIVE_FEATURES,
    build_feature_frame,
    feature_columns_blind,
    feature_columns_full,
    split_indices,
)


def test_feature_blind_excludes_sensitive() -> None:
    blind = set(feature_columns_blind())
    full = set(feature_columns_full())
    sens = set(SENSITIVE_FEATURES)
    assert blind & sens == set()
    assert sens.issubset(full)


def test_build_feature_frame_shapes() -> None:
    df = generate(default_spec(n_rows=1500, seed=21))
    feats = build_feature_frame(df)
    assert len(feats.X) == 1500
    assert "yoe_sq" in feats.X.columns
    assert "is_metro" in feats.X.columns
    assert feats.y_base.shape == (1500,)
    assert feats.y_tcc.shape == (1500,)


def test_temporal_split_disjoint_and_ordered() -> None:
    df = generate(default_spec(n_rows=2000, seed=22))
    tr, va, te = split_indices(df, val_fraction=0.15, test_fraction=0.15)
    assert len(set(tr) & set(va)) == 0
    assert len(set(va) & set(te)) == 0
    max_train = df.loc[tr, "observed_at"].max()
    min_val = df.loc[va, "observed_at"].min()
    assert max_train <= min_val
    assert len(te) > 0


def test_no_nan_in_numeric_features() -> None:
    df = generate(default_spec(n_rows=500, seed=23))
    feats = build_feature_frame(df)
    numeric = feats.X.select_dtypes(include=[np.number])
    assert numeric.isna().sum().sum() == 0
