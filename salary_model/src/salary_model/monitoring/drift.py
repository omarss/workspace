"""Population Stability Index (PSI) drift detector.

PSI is the standard metric for distribution shift between a reference (training) sample
and a current sample. Per feature:

    PSI = sum over bins b of: (p_curr_b - p_ref_b) * ln(p_curr_b / p_ref_b)

Rules of thumb (industry-standard, see e.g. SAS docs):

- PSI < 0.10:  no significant shift
- 0.10 <= PSI < 0.25:  moderate shift, investigate
- PSI >= 0.25:  significant shift, retrain candidate

We compute PSI per feature using deciles for numerics and the empirical distribution
for categoricals. Output is a typed report plus a Markdown summary.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

PSI_WARN: float = 0.10
PSI_ALERT: float = 0.25
PSI_EPS: float = 1e-6  # smoothing to avoid log(0)


@dataclass(frozen=True)
class FeatureDrift:
    feature: str
    psi: float
    n_ref: int
    n_curr: int
    severity: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DriftReport:
    reference_n: int
    current_n: int
    per_feature: tuple[FeatureDrift, ...]

    @property
    def max_psi(self) -> float:
        return max((f.psi for f in self.per_feature), default=0.0)

    @property
    def alerts(self) -> tuple[FeatureDrift, ...]:
        return tuple(f for f in self.per_feature if f.severity == "alert")

    @property
    def warnings(self) -> tuple[FeatureDrift, ...]:
        return tuple(f for f in self.per_feature if f.severity == "warn")

    def to_markdown(self) -> str:
        lines = [
            "# Drift report (PSI)",
            "",
            f"- reference n: `{self.reference_n}`",
            f"- current n:   `{self.current_n}`",
            f"- max PSI:     `{self.max_psi:.4f}`",
            f"- alerts:      `{len(self.alerts)}`",
            f"- warnings:    `{len(self.warnings)}`",
            "",
            "| feature | psi | severity | n_ref | n_curr |",
            "|---|---:|---|---:|---:|",
        ]
        ordered = sorted(self.per_feature, key=lambda f: f.psi, reverse=True)
        for f in ordered:
            lines.append(f"| `{f.feature}` | {f.psi:.4f} | {f.severity} | {f.n_ref} | {f.n_curr} |")
        return "\n".join(lines) + "\n"

    def to_json(self) -> str:
        payload = {
            "reference_n": self.reference_n,
            "current_n": self.current_n,
            "max_psi": self.max_psi,
            "alerts": [f.to_dict() for f in self.alerts],
            "per_feature": [f.to_dict() for f in self.per_feature],
        }
        return json.dumps(payload, indent=2)


def _severity(psi: float) -> str:
    if psi >= PSI_ALERT:
        return "alert"
    if psi >= PSI_WARN:
        return "warn"
    return "ok"


def _psi_numeric(ref: np.ndarray, curr: np.ndarray, *, n_bins: int = 10) -> float:
    """PSI on a numeric feature using deciles of the reference distribution."""
    ref = ref[~np.isnan(ref)]
    curr = curr[~np.isnan(curr)]
    if ref.size == 0 or curr.size == 0:
        return 0.0
    qs = np.linspace(0.0, 1.0, n_bins + 1)
    edges = np.unique(np.quantile(ref, qs))
    if edges.size < 2:
        return 0.0
    edges[0] = -np.inf
    edges[-1] = np.inf
    ref_counts, _ = np.histogram(ref, bins=edges)
    curr_counts, _ = np.histogram(curr, bins=edges)
    p_ref = ref_counts / max(ref.size, 1) + PSI_EPS
    p_curr = curr_counts / max(curr.size, 1) + PSI_EPS
    return float(np.sum((p_curr - p_ref) * np.log(p_curr / p_ref)))


def _psi_categorical(ref: pd.Series, curr: pd.Series) -> float:
    """PSI on a categorical feature using the empirical category distribution."""
    cats = sorted(set(ref.dropna().unique()) | set(curr.dropna().unique()))
    if not cats:
        return 0.0
    ref_counts = ref.value_counts().reindex(cats).fillna(0).to_numpy(dtype=float)
    curr_counts = curr.value_counts().reindex(cats).fillna(0).to_numpy(dtype=float)
    p_ref = ref_counts / max(ref_counts.sum(), 1.0) + PSI_EPS
    p_curr = curr_counts / max(curr_counts.sum(), 1.0) + PSI_EPS
    return float(np.sum((p_curr - p_ref) * np.log(p_curr / p_ref)))


def compute_drift(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    *,
    features: list[str] | None = None,
) -> DriftReport:
    """Compute the per-feature PSI report.

    Args:
        reference: training-time snapshot (post-feature-build).
        current: current observations (post-feature-build), same columns.
        features: subset to evaluate; defaults to the intersection of columns.
    """
    feats = features or [c for c in reference.columns if c in current.columns]
    out: list[FeatureDrift] = []
    for c in feats:
        ref = reference[c]
        cur = current[c]
        if pd.api.types.is_numeric_dtype(ref) and pd.api.types.is_numeric_dtype(cur):
            psi = _psi_numeric(ref.to_numpy(dtype=float), cur.to_numpy(dtype=float))
        else:
            psi = _psi_categorical(ref.astype(str), cur.astype(str))
        out.append(
            FeatureDrift(
                feature=c, psi=float(psi),
                n_ref=int(ref.size), n_curr=int(cur.size),
                severity=_severity(float(psi)),
            )
        )
    return DriftReport(
        reference_n=len(reference),
        current_n=len(current),
        per_feature=tuple(out),
    )


def write_report(report: DriftReport, out_dir: Path) -> tuple[Path, Path]:
    """Write the drift report to ``drift.md`` and ``drift.json``; return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "drift.md"
    json_path = out_dir / "drift.json"
    md_path.write_text(report.to_markdown(), encoding="utf-8")
    json_path.write_text(report.to_json(), encoding="utf-8")
    return md_path, json_path
