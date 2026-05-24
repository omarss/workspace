from __future__ import annotations

import pandas as pd

from salary_model.models.fairness import reweight_sensitive


def test_reweight_balances_within_cell() -> None:
    df = pd.DataFrame(
        {
            "family": ["SWE"] * 6,
            "level": ["IC3"] * 6,
            "gender": ["M", "M", "M", "M", "F", "F"],
            "is_saudi": [True, True, True, True, True, True],
        }
    )
    w = reweight_sensitive(df, family_col="family", level_col="level")
    # Male rows should have weight < female rows because there are more of them
    m_w = w[df["gender"] == "M"].mean()
    f_w = w[df["gender"] == "F"].mean()
    assert f_w > m_w


def test_reweight_clip_caps_extremes() -> None:
    df = pd.DataFrame(
        {
            "family": ["SWE"] * 11,
            "level": ["IC3"] * 11,
            "gender": ["M"] * 10 + ["F"],
            "is_saudi": [True] * 11,
        }
    )
    w = reweight_sensitive(df, family_col="family", level_col="level", clip=5.0)
    assert (w <= 5.0).all()
    assert (w >= 1.0 / 5.0).all()
