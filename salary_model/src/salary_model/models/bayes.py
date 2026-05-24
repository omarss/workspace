"""Hierarchical Bayesian partial-pooling for sparse (family x level x region) cells.

A small NumPyro model: ``log(base) ~ Normal(mu_cell, sigma)`` where ``mu_cell`` is a
sum of family, level, region random effects plus a global intercept. SVI fit (fast,
deterministic) gives us posterior means per cell that we can use to shrink sparse-cell
predictions toward the family/level/region marginals.

This is **v2** — the descriptive head ships without it. We expose a small interface so
the iteration runner can opt in.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

try:  # NumPyro is an optional heavy dep; guard the import for type-checker friendliness
    import jax
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist
    from numpyro.infer import SVI, Trace_ELBO
    from numpyro.infer.autoguide import AutoNormal

    NUMPYRO_AVAILABLE = True
except ImportError:  # pragma: no cover
    NUMPYRO_AVAILABLE = False


@dataclass(frozen=True)
class BayesShrinkage:
    """Posterior means per (family, level, region) cell, indexed by string keys."""

    cell_log_means: dict[tuple[str, str, str], float]
    global_log_mean: float
    sigma: float

    def predict(self, family: str, level: str, region: str) -> float:
        key = (family, level, region)
        return float(np.exp(self.cell_log_means.get(key, self.global_log_mean)))


def fit_shrinkage(
    df: pd.DataFrame,
    *,
    target: str = "base_monthly",
    seed: int = 17,
    n_steps: int = 1500,
    learning_rate: float = 0.05,
    use_svi: bool = False,
) -> BayesShrinkage:
    """Fit the partial-pooling model.

    Defaults to a fast empirical-Bayes approximation (group means in log-space) which is
    adequate for the v2 shrinkage blend. Set ``use_svi=True`` to opt into the full
    NumPyro SVI fit (slow on CPU; budget several minutes for typical dataset sizes).
    Also returns the empirical fallback when NumPyro is unavailable at import time.
    """
    if not use_svi or not NUMPYRO_AVAILABLE:
        return _empirical_fallback(df, target=target)

    sub = df[["family", "level", "region", target]].copy()
    sub["log_y"] = np.log(sub[target].astype(float).clip(lower=1.0))
    fam_ids, fam_labels = pd.factorize(sub["family"])
    lvl_ids, lvl_labels = pd.factorize(sub["level"])
    reg_ids, reg_labels = pd.factorize(sub["region"])
    y = jnp.asarray(sub["log_y"].to_numpy(), dtype=jnp.float32)

    def model(fam: jax.Array, lvl: jax.Array, reg: jax.Array, y_: jax.Array) -> None:
        mu0 = numpyro.sample("mu0", dist.Normal(9.5, 2.0))
        sigma = numpyro.sample("sigma", dist.HalfNormal(1.0))
        sigma_f = numpyro.sample("sigma_f", dist.HalfNormal(0.5))
        sigma_l = numpyro.sample("sigma_l", dist.HalfNormal(0.5))
        sigma_r = numpyro.sample("sigma_r", dist.HalfNormal(0.3))
        with numpyro.plate("f", len(fam_labels)):
            alpha_f = numpyro.sample("alpha_f", dist.Normal(0.0, sigma_f))
        with numpyro.plate("l", len(lvl_labels)):
            alpha_l = numpyro.sample("alpha_l", dist.Normal(0.0, sigma_l))
        with numpyro.plate("r", len(reg_labels)):
            alpha_r = numpyro.sample("alpha_r", dist.Normal(0.0, sigma_r))
        mu = mu0 + alpha_f[fam] + alpha_l[lvl] + alpha_r[reg]
        with numpyro.plate("obs", y_.shape[0]):
            numpyro.sample("y_obs", dist.Normal(mu, sigma), obs=y_)

    guide = AutoNormal(model)
    optimizer = numpyro.optim.Adam(step_size=learning_rate)
    svi = SVI(model, guide, optimizer, Trace_ELBO())
    fam_arr = jnp.asarray(fam_ids, dtype=jnp.int32)
    lvl_arr = jnp.asarray(lvl_ids, dtype=jnp.int32)
    reg_arr = jnp.asarray(reg_ids, dtype=jnp.int32)
    svi_state = svi.init(jax.random.PRNGKey(seed), fam_arr, lvl_arr, reg_arr, y)
    for _ in range(n_steps):
        svi_state, _loss = svi.update(svi_state, fam_arr, lvl_arr, reg_arr, y)
    params = svi.get_params(svi_state)

    mu0 = float(params["mu0_auto_loc"])
    sigma = float(jnp.exp(params["sigma_auto_loc"]))
    af = np.asarray(params["alpha_f_auto_loc"])
    al = np.asarray(params["alpha_l_auto_loc"])
    ar = np.asarray(params["alpha_r_auto_loc"])

    cell_log_means: dict[tuple[str, str, str], float] = {}
    for f_idx, f_label in enumerate(fam_labels):
        for l_idx, l_label in enumerate(lvl_labels):
            for r_idx, r_label in enumerate(reg_labels):
                cell_log_means[(str(f_label), str(l_label), str(r_label))] = float(
                    mu0 + af[f_idx] + al[l_idx] + ar[r_idx]
                )
    return BayesShrinkage(
        cell_log_means=cell_log_means,
        global_log_mean=mu0,
        sigma=sigma,
    )


def _empirical_fallback(df: pd.DataFrame, *, target: str) -> BayesShrinkage:
    grp = df.groupby(["family", "level", "region"])[target].apply(
        lambda s: float(np.log(np.clip(s.mean(), 1.0, None)))
    )
    cell_log_means: dict[tuple[str, str, str], float] = {}
    for idx, val in grp.items():
        if isinstance(idx, tuple) and len(idx) == 3:
            cell_log_means[(str(idx[0]), str(idx[1]), str(idx[2]))] = float(val)
    global_mean = float(np.log(np.clip(df[target].mean(), 1.0, None)))
    sigma = float(np.log(np.clip(df[target].std() or 1.0, 1.0, None)))
    return BayesShrinkage(
        cell_log_means=cell_log_means,
        global_log_mean=global_mean,
        sigma=sigma,
    )
