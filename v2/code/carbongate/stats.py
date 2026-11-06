"""Summary statistics over held-out months (the month is the unit of replication)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

CI_LEVEL = 0.95


def t_ci(x: np.ndarray, level: float = CI_LEVEL) -> tuple[float, float, float, float]:
    """Mean, sample std, and two-sided t confidence interval."""
    x = np.asarray(x, float)
    m, sd = float(x.mean()), float(x.std(ddof=1)) if len(x) > 1 else 0.0
    if len(x) < 2 or sd == 0:
        return m, sd, m, m
    h = stats.t.ppf(0.5 + level / 2, len(x) - 1) * sd / np.sqrt(len(x))
    return m, sd, m - h, m + h


def summarise(df: pd.DataFrame, keys: list[str], held_out: list[str]) -> list[dict]:
    """Seed-average within each month, then mean/std/CI across held-out months."""
    out = []
    d = df[df["month"].isin(held_out)]
    for k, g in d.groupby(keys, sort=False, dropna=False):
        k = k if isinstance(k, tuple) else (k,)
        per_month = g.groupby("month").agg(
            reduction=("reduction", "mean"), delay_p50_min=("delay_p50_min", "mean"),
            delay_p95_min=("delay_p95_min", "mean"), deferral_rate=("deferral_rate", "mean"),
            fallback_rate=("fallback_rate", "mean"), harmful=("harmful_deferral_rate", "mean"))
        valid = per_month["reduction"].dropna().to_numpy()
        m, sd, lo, hi = t_ci(valid) if len(valid) else (float("nan"),) * 4
        seed_tot = g.groupby("seed")[["base_kg", "policy_kg", "saved_kg"]].sum()
        row = dict(zip(keys, k))
        row.update({
            "n_months": int(len(valid)), "n_seeds": int(g["seed"].nunique()),
            "reduction_mean": m, "reduction_std_months": sd, "reduction_ci_lo": lo, "reduction_ci_hi": hi,
            "reduction_min_month": float(per_month["reduction"].min()),
            "reduction_max_month": float(per_month["reduction"].max()),
            "reduction_std_cells": float(g["reduction"].std(ddof=1)),
            "base_kg_per_seed": float(seed_tot["base_kg"].mean()),
            "policy_kg_per_seed": float(seed_tot["policy_kg"].mean()),
            "saved_kg_per_seed": float(seed_tot["saved_kg"].mean()),
            "pooled_reduction": float(seed_tot["saved_kg"].sum() / seed_tot["base_kg"].sum()),
            "delay_p50_min": float(per_month["delay_p50_min"].mean()),
            "delay_p95_min": float(per_month["delay_p95_min"].mean()),
            "delay_p95_h": float(per_month["delay_p95_min"].mean() / 60),
            "delay_max_min": float(g["delay_max_min"].max()),
            "deferral_rate": float(per_month["deferral_rate"].mean()),
            "harmful_deferral_rate": float(per_month["harmful"].mean()),
            "fallback_rate": float(per_month["fallback_rate"].mean()),
            "sla_violations": int(g["sla_violations"].sum()),
            "sla_violation_rate": float(g["sla_violations"].sum() / g["n_deploy"].sum()),
            "n_deploy_total": int(g["n_deploy"].sum()),
            "n_urgent_total": int(g["n_urgent"].sum()),
            "bypass_rate": float(g["n_urgent"].sum() / g["n_deploy"].sum()),
        })
        out.append(row)
    return out


def with_pct(row: dict) -> dict:
    """Add `<key>_pct` (value x 100) for every reduction/rate/capture field, as printed in the paper's tables."""
    for k, v in list(row.items()):
        if isinstance(v, float) and any(s in k for s in ("reduction", "rate", "diff", "ci_", "mean", "std")):
            row[f"{k}_pct"] = 100 * v
    return row


def paired_diff(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    m, sd, lo, hi = t_ci(np.asarray(a) - np.asarray(b))
    w = stats.wilcoxon(a, b) if len(a) > 1 and np.any(np.asarray(a) != np.asarray(b)) else None
    return {"mean_diff": m, "std_diff": sd, "ci_lo": lo, "ci_hi": hi,
            "wilcoxon_p": float(w.pvalue) if w is not None else 1.0, "n": int(len(a))}
