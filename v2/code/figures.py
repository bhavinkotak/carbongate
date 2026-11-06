"""Redraw every data figure from the files in results/ (no figure is drawn from hand-entered numbers)."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

COL_W = 3.45  # inches; IEEE column is 8.86 cm
plt.rcParams.update({"font.size": 7.5, "axes.titlesize": 7.5, "legend.fontsize": 6.5, "pdf.fonttype": 42,
                     "axes.spines.top": False, "axes.spines.right": False})
COLORS = {"threshold": "#888888", "deferral": "#1f5fa8", "oracle": "#c0392b"}
LABELS = {"threshold": "Static threshold", "deferral": "CarbonGate-F", "oracle": "Oracle"}


def _summary(results: Path) -> list[dict]:
    return json.loads((results / "summary.json").read_text())


def fig_profile(results: Path, out: Path) -> None:
    prof = pd.read_csv(results / "hourly_profile.csv")
    fig, ax = plt.subplots(figsize=(COL_W, 2.1))
    for season, ls, lab in (("winter", "-", "Dec-Feb"), ("summer", "--", "Jun-Aug"), ("other", ":", "other months")):
        p = prof[prof["season"] == season]
        ax.plot(p["hour"], p["actual_mean"], ls, color="k", lw=1, label=lab)
    ax.set_xlabel("Local hour (Europe/London)")
    ax.set_ylabel("Mean intensity (gCO$_2$/kWh)")
    ax2 = ax.twinx()
    r = prof.drop_duplicates("hour")
    ax2.fill_between(r["hour"], 0, r["rate_mean"], step="post", color=COLORS["deferral"], alpha=0.18, lw=0)
    ax2.set_ylabel("Arrivals per slot (simulated)", color=COLORS["deferral"])
    ax2.spines["right"].set_visible(True)
    ax.set_xlim(0, 24)
    ax.legend(loc="lower left", frameon=False, ncol=3, bbox_to_anchor=(0, 1.0), handlelength=1.8)
    fig.tight_layout()
    fig.savefig(out / "fig_profile.pdf")
    plt.close(fig)


def fig_deadline(results: Path, out: Path) -> None:
    s = [r for r in _summary(results) if r["experiment"] == "main" and r["policy"] != "immediate"]
    fig, ax = plt.subplots(figsize=(COL_W, 2.0))
    for pol in ("threshold", "deferral", "oracle"):
        rr = sorted((r for r in s if r["policy"] == pol), key=lambda r: r["max_delay_h"])
        x = [r["max_delay_h"] for r in rr]
        y = [100 * r["reduction_mean"] for r in rr]
        err = [[100 * (r["reduction_mean"] - r["reduction_ci_lo"]) for r in rr],
               [100 * (r["reduction_ci_hi"] - r["reduction_mean"]) for r in rr]]
        ax.errorbar(x, y, yerr=err, marker="o", ms=3, capsize=2, lw=1, color=COLORS[pol], label=LABELS[pol])
    ax.axhline(5, ls="--", lw=0.7, color="k")
    ax.text(5.5, 4.4, "H1 bound", fontsize=6.5, va="top")
    ax.set_xlabel("Maximum added delay $D$ (h)")
    ax.set_ylabel("Emission reduction (%)")
    ax.set_xticks([2, 4, 8])
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / "fig_deadline.pdf")
    plt.close(fig)


def fig_months(results: Path, out: Path) -> None:
    df = pd.read_csv(results / "per_month.csv")
    held = json.loads((results / "data_stats.json").read_text())["config"]["held_out"]
    d = df[(df["experiment"] == "main") & (df["max_delay_h"] == 4) & df["month"].isin(held)]
    fig, ax = plt.subplots(figsize=(COL_W, 2.0))
    for pol in ("threshold", "deferral", "oracle"):
        g = d[d["policy"] == pol].groupby("month")["reduction"].agg(["mean", "min", "max"]).reindex(held)
        ax.plot(range(len(held)), 100 * g["mean"], marker="o", ms=3, lw=1, color=COLORS[pol], label=LABELS[pol])
        ax.fill_between(range(len(held)), 100 * g["min"], 100 * g["max"], color=COLORS[pol], alpha=0.15, lw=0)
    ax.set_xticks(range(len(held)))
    ax.set_xticklabels([m[2:] for m in held], rotation=60)
    ax.set_ylabel("Emission reduction (%)")
    ax.set_xlabel("Held-out month (shaded: seed min to max)")
    fig.legend(*ax.get_legend_handles_labels(), frameon=False, ncol=3, loc="upper center",
               bbox_to_anchor=(0.5, 1.0), handlelength=1.5, columnspacing=1.2)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(out / "fig_months.pdf")
    plt.close(fig)


def fig_fallback(results: Path, out: Path) -> None:
    s = [r for r in _summary(results) if r["experiment"] == "fallback" and r["policy"] == "deferral"]
    scen = [(0.05, 0.0), (0.2, 0.0), (0.5, 0.0), (0.0, 0.1)]
    names = ["out 5%", "out 20%", "out 50%", "t/o 10%"]
    fbs = [("fail_open", "Fail-open", "#1f5fa8"), ("fail_closed", "Fail-closed", "#c0392b"),
           ("cached_persistence", "Cached persistence", "#2e8b57")]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(COL_W, 2.6), sharex=True)
    w = 0.26
    for j, (fb, lab, col) in enumerate(fbs):
        red, viol = [], []
        for of, tp in scen:
            r = next(r for r in s if r["fallback"] == fb and r["outage_frac"] == of and r["timeout_prob"] == tp)
            red.append(100 * r["reduction_mean"])
            viol.append(100 * r["sla_violation_rate"])
        xs = [i + (j - 1) * w for i in range(len(scen))]
        a1.bar(xs, red, w, color=col, label=lab)
        a2.bar(xs, viol, w, color=col)
    a1.set_ylabel("Reduction (%)")
    a2.set_ylabel("SLA violations (%)")
    a2.set_xticks(range(len(scen)))
    a2.set_xticklabels(names)
    fig.legend(*a1.get_legend_handles_labels(), frameon=False, ncol=3, loc="upper center",
               bbox_to_anchor=(0.5, 1.0), handlelength=1.5, columnspacing=1.2)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out / "fig_fallback.pdf")
    plt.close(fig)


def make_all(results: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    fig_profile(results, out)
    fig_deadline(results, out)
    fig_months(results, out)
    fig_fallback(results, out)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    make_all(root / "results", root / "paper" / "figures")
