"""Single entry point: download/cache data, run every experiment with fixed seeds, write results/, redraw figures.

Usage:  python code/run_all.py            (offline after the first run; raw API responses are cached)
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from carbongate import data, workload  # noqa: E402
from carbongate.gate import Fallback  # noqa: E402
from carbongate.sim import (DAY_SLOTS, SLOT_MIN, Scenario, Signals, capacity_start_times,  # noqa: E402
                            cumulative, month_metrics, persistence, start_times)
from carbongate.stats import paired_diff, summarise, t_ci, with_pct  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW, RESULTS, FIGDIR = ROOT / "data" / "raw", ROOT / "results", ROOT / "paper" / "figures"

SEEDS = (0, 1, 2, 3, 4)
DEADLINES_H = (2, 4, 8)
PRIMARY_H = 4
DELTA = 0.05
H1_MIN_REDUCTION = 0.05
V1_CLAIMED_LOWER = 0.23
NOISE_SIGMAS = (10, 25, 50)
DELTAS = (0.0, 0.05, 0.10, 0.20)
URGENT_GRID = (0.0, 0.10, 0.30)
OUTAGE_FRACS = (0.05, 0.20, 0.50)
TIMEOUT_PROB = 0.10
SCALES = (1, 100)
CALIBRATION = "2025-11"


def months() -> list[tuple[str, float, float]]:
    out, y, m = [], 2025, 11
    for _ in range(12):
        lo = datetime(y, m, 1, tzinfo=UTC)
        y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
        hi = datetime(y2, m2, 1, tzinfo=UTC)
        out.append((f"{y}-{m:02d}", (lo - data.START).total_seconds() / 60, (hi - data.START).total_seconds() / 60))
        y, m = y2, m2
    return out


MONTHS = months()
HELD_OUT = [m for m, _, _ in MONTHS if m != CALIBRATION]


def run_scenario(sc: Scenario, wl: workload.Workload, sig: Signals, cum: np.ndarray, seed: int,
                 tag: dict, salt: int = 0) -> list[dict]:
    rng = np.random.default_rng([seed, 7919, salt])
    start, fb = start_times(sc, wl, sig, rng)
    rows = []
    for label, lo, hi in MONTHS:
        r = {**tag, "policy": sc.policy, "max_delay_h": sc.max_delay_h, "forecaster": sc.forecaster,
             "delta": sc.delta, "outage_frac": sc.outage_frac, "timeout_prob": sc.timeout_prob,
             "fallback": sc.fallback.value, "seed": seed, "month": label}
        r.update(month_metrics(sc, wl, start, fb, sig, cum, lo, hi))
        rows.append(r)
    return rows


def data_stats(nat: dict, actual: np.ndarray, reg: dict, gaps: dict) -> dict:
    slots = data.slot_index()
    ho = np.zeros(len(slots), bool)
    for label, lo, hi in MONTHS:
        if label in HELD_OUT:
            ho[int(lo // SLOT_MIN):int(hi // SLOT_MIN)] = True
    f, a = nat["forecast"], nat["actual"]
    both = ho & ~np.isnan(f) & ~np.isnan(a)
    pers = persistence(a)
    bp = ho & ~np.isnan(pers) & ~np.isnan(a)
    daily = actual[: (len(actual) // DAY_SLOTS) * DAY_SLOTS].reshape(-1, DAY_SLOTS)
    ho_days = ho[: daily.size].reshape(-1, DAY_SLOTS).all(axis=1)
    rng_daily = daily.max(axis=1) - daily.min(axis=1)
    monthly = {lab: float(actual[int(lo // SLOT_MIN):int(hi // SLOT_MIN)].mean()) for lab, lo, hi in MONTHS}
    return {
        "n_slots_record": len(slots), "n_slots_held_out": int(ho.sum()),
        "missing_forecast_slots": int(np.isnan(f[: len(slots)]).sum()),
        "missing_actual_slots": int(np.isnan(a).sum()), "interpolated_actual_slots": gaps["national"],
        "held_out_actual_mean": float(actual[ho].mean()), "held_out_actual_std": float(actual[ho].std()),
        "held_out_actual_min": float(actual[ho].min()), "held_out_actual_max": float(actual[ho].max()),
        "held_out_daily_range_mean": float(rng_daily[ho_days].mean()),
        "neso_forecast_mae": float(np.abs(f[both] - a[both]).mean()),
        "neso_forecast_rmse": float(np.sqrt(((f[both] - a[both]) ** 2).mean())),
        "neso_forecast_bias": float((f[both] - a[both]).mean()),
        "persistence_mae": float(np.abs(pers[bp] - a[bp]).mean()),
        "monthly_mean_actual": monthly,
        "regional_mean_forecast": {data.REGIONS[r]: float(np.nanmean(v[ho])) for r, v in reg.items()},
        "regional_interpolated_slots": {data.REGIONS[r]: gaps[r] for r in reg},
        "regional_zero_fraction": {data.REGIONS[r]: float((v[ho] == 0).mean()) for r, v in reg.items()},
    }


def hourly_profile(actual: np.ndarray, rates: np.ndarray) -> pd.DataFrame:
    slots = data.slot_index()
    loc = pd.DatetimeIndex(slots).tz_convert(workload.LONDON)
    df = pd.DataFrame({"hour": loc.hour + loc.minute / 60, "month": loc.month, "actual": actual,
                       "rate": rates})
    df["season"] = np.where(df["month"].isin([12, 1, 2]), "winter",
                            np.where(df["month"].isin([6, 7, 8]), "summer", "other"))
    prof = df.groupby(["season", "hour"]).agg(actual_mean=("actual", "mean")).reset_index()
    arr = df.groupby("hour").agg(rate_mean=("rate", "mean")).reset_index()
    return prof.merge(arr, on="hour")


def latency_stats(path: Path) -> dict:
    d = json.loads(path.read_text())
    s = np.array([x["seconds"] for x in d["samples"]])
    ok = np.array([x["ok"] for x in d["samples"]])
    return {"endpoint": d["endpoint"], "retrieved_utc": d["retrieved_utc"], "n_calls": int(len(s)),
            "n_ok": int(ok.sum()), "p50_s": float(np.percentile(s, 50)), "p95_s": float(np.percentile(s, 95)),
            "max_s": float(s.max()), "gate_timeout_s": data.GATE_TIMEOUT_S,
            "n_over_timeout": int((s > data.GATE_TIMEOUT_S).sum())}


def main() -> None:
    t0 = time.time()
    RESULTS.mkdir(parents=True, exist_ok=True)
    nat_paths = data.fetch_all(RAW, "national")
    reg_paths = data.fetch_all(RAW, "regional")
    probe = data.latency_probe(RAW)
    data.write_sources(ROOT / "data", nat_paths, reg_paths, probe)
    nat = data.load_national(nat_paths)
    nat["actual"], n_zero = data.clean_national_actual(nat["actual"])
    reg_raw = data.load_regional(reg_paths)
    actual, n_gap = data.interpolate_gaps(nat["actual"])
    gaps = {"national": n_gap}
    reg_score = {}
    for r, v in reg_raw.items():
        reg_score[r], gaps[r] = data.interpolate_gaps(v)
    cum = cumulative(actual)
    n_slots = len(actual)

    cal_lo, cal_hi = int(MONTHS[0][1] // SLOT_MIN), int(MONTHS[0][2] // SLOT_MIN)
    theta = float(np.nanmedian(nat["forecast"][cal_lo:cal_hi]))
    stats = data_stats(nat, actual, reg_raw, gaps)
    stats["static_threshold_theta"] = theta
    stats["zero_actual_slots_set_missing"] = n_zero
    stats["latency_probe"] = latency_stats(probe)
    slots = data.slot_index()
    rates = workload.slot_rates(slots)
    hourly_profile(actual, rates).to_csv(RESULTS / "hourly_profile.csv", index=False)

    rows: list[dict] = []
    for seed in SEEDS:
        wl = workload.simulate(rates, seed)
        rng = np.random.default_rng([seed, 31337])
        fc = {"neso": nat["forecast"], "persistence": persistence(nat["actual"])}
        for sg in NOISE_SIGMAS:
            fc[f"neso+noise{sg}"] = nat["forecast"] + rng.normal(0, sg, size=n_slots)
        sig = Signals(score=actual, forecasts=fc, persistence_source=nat["actual"])
        base_tag = {"region": "GB national", "urgent_fraction": workload.URGENT_FRACTION,
                    "shape": "working_hours", "scale": 1, "capped": False}

        # E1 main grid
        for h in DEADLINES_H:
            for pol in ("immediate", "threshold", "deferral", "oracle"):
                sc = Scenario(pol, h, "neso", DELTA, theta)
                rows += run_scenario(sc, wl, sig, cum, seed, {**base_tag, "experiment": "main"})
        # E2 forecaster ablation
        for name in ("persistence", *[f"neso+noise{s}" for s in NOISE_SIGMAS]):
            sc = Scenario("deferral", PRIMARY_H, name, DELTA, theta)
            rows += run_scenario(sc, wl, sig, cum, seed, {**base_tag, "experiment": "forecaster"})
        # E3 deferral margin
        for dl in DELTAS:
            sc = Scenario("deferral", PRIMARY_H, "neso", dl, theta)
            rows += run_scenario(sc, wl, sig, cum, seed, {**base_tag, "experiment": "delta"})
        # E7 forecaster outages, timeouts, and fallbacks
        for pol in ("deferral", "threshold"):
            for fb in Fallback:
                for j, (of, tp) in enumerate([*[(o, 0.0) for o in OUTAGE_FRACS], (0.0, TIMEOUT_PROB)]):
                    sc = Scenario(pol, PRIMARY_H, "neso", DELTA, theta, of, tp, fb)
                    rows += run_scenario(sc, wl, sig, cum, seed, {**base_tag, "experiment": "fallback"}, salt=j)
        # E4 urgent fraction and E5 arrival shape (new workloads, same seed)
        for uf in URGENT_GRID:
            wl_u = workload.simulate(rates, seed, urgent_fraction=uf)
            for pol in ("immediate", "deferral"):
                sc = Scenario(pol, PRIMARY_H, "neso", DELTA, theta)
                rows += run_scenario(sc, wl_u, sig, cum, seed,
                                     {**base_tag, "urgent_fraction": uf, "experiment": "urgent"})
        wl_flat = workload.simulate(workload.slot_rates(slots, "uniform"), seed)
        for pol in ("immediate", "deferral", "oracle"):
            sc = Scenario(pol, PRIMARY_H, "neso", DELTA, theta)
            rows += run_scenario(sc, wl_flat, sig, cum, seed, {**base_tag, "shape": "uniform", "experiment": "shape"})
        # E6 regions: decisions on day-ahead persistence of the regional series, scored on that series (proxy)
        for r, score in [(0, actual), *reg_score.items()]:
            name = "GB national" if r == 0 else data.REGIONS[r]
            raw = nat["actual"] if r == 0 else reg_raw[r]
            rsig = Signals(score=score, forecasts={"persistence": persistence(raw)}, persistence_source=raw)
            rcum = cumulative(score)
            for pol in ("immediate", "deferral", "oracle"):
                sc = Scenario(pol, PRIMARY_H, "persistence", DELTA, theta)
                rows += run_scenario(sc, wl, rsig, rcum, seed, {**base_tag, "region": name, "experiment": "region"})

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS / "per_month.csv", index=False)
    keys = ["experiment", "region", "shape", "urgent_fraction", "policy", "max_delay_h", "forecaster", "delta",
            "outage_frac", "timeout_prob", "fallback"]
    summary = summarise(df, keys, HELD_OUT)

    cap_rows = capacity_experiment(rates, actual, nat, cum, n_slots)
    cap_df = pd.DataFrame(cap_rows)
    cap_df.to_csv(RESULTS / "capacity_per_month.csv", index=False)
    cap_summary = summarise(cap_df, ["experiment", "scale", "policy", "capped", "max_delay_h"], HELD_OUT)
    peak = cap_df[cap_df["month"].isin(HELD_OUT)].groupby(["scale", "policy", "capped"])["peak_ratio"].mean()
    for row in cap_summary:
        row["peak_ratio"] = float(peak.get((row["scale"], row["policy"], row["capped"]), np.nan))
        row["cap"] = float(cap_df[(cap_df["scale"] == row["scale"])]["cap"].mean())

    def pick(**kw):
        for row in summary:
            if all(row.get(k) == v for k, v in kw.items()):
                return row
        raise KeyError(kw)

    def per_month_red(**kw):
        g = df[df["month"].isin(HELD_OUT)]
        for k, v in kw.items():
            g = g[g[k] == v]
        return g.groupby("month")["reduction"].mean().reindex(HELD_OUT).to_numpy()

    prim = pick(experiment="main", policy="deferral", max_delay_h=PRIMARY_H)
    lo, hi = prim["reduction_ci_lo"], prim["reduction_ci_hi"]
    if lo > H1_MIN_REDUCTION and prim["sla_violations"] == 0:
        v1 = "SUPPORTED"
    elif hi < H1_MIN_REDUCTION or prim["sla_violations"] > 0:
        v1 = "REFUTED"
    else:
        v1 = "INCONCLUSIVE"
    v2 = "SUPPORTED" if lo > V1_CLAIMED_LOWER else ("REFUTED" if hi < V1_CLAIMED_LOWER else "INCONCLUSIVE")
    comparisons = {}
    for h in DEADLINES_H:
        d_red = per_month_red(experiment="main", policy="deferral", max_delay_h=h)
        comparisons[f"deferral_minus_threshold_{h}h"] = paired_diff(
            d_red, per_month_red(experiment="main", policy="threshold", max_delay_h=h))
        o_red = per_month_red(experiment="main", policy="oracle", max_delay_h=h)
        comparisons[f"oracle_minus_deferral_{h}h"] = paired_diff(o_red, d_red)
        comparisons[f"oracle_capture_{h}h"] = dict(zip(("mean", "std", "ci_lo", "ci_hi"), t_ci(d_red / o_red)))
    comparisons["neso_minus_persistence_4h"] = paired_diff(
        per_month_red(experiment="main", policy="deferral", max_delay_h=PRIMARY_H),
        per_month_red(experiment="forecaster", forecaster="persistence"))

    verdict = {
        "H1": {"verdict": v1, "endpoint": "mean held-out relative reduction, CarbonGate-F, 4 h SLA, NESO forecast",
               "threshold": H1_MIN_REDUCTION, "mean": prim["reduction_mean"], "ci95": [lo, hi],
               "std_months": prim["reduction_std_months"], "n_months": prim["n_months"],
               "n_seeds": prim["n_seeds"], "sla_violations": prim["sla_violations"],
               "numerator_kg_per_seed": prim["saved_kg_per_seed"],
               "denominator_kg_per_seed": prim["base_kg_per_seed"]},
        "H2_v1_claim": {"verdict": v2, "threshold": V1_CLAIMED_LOWER, "mean": prim["reduction_mean"],
                        "ci95": [lo, hi]},
    }
    (RESULTS / "verdict.json").write_text(json.dumps(verdict, indent=2))
    (RESULTS / "summary.json").write_text(json.dumps([with_pct(r) for r in summary], indent=1))
    (RESULTS / "capacity_summary.json").write_text(json.dumps([with_pct(r) for r in cap_summary], indent=1))
    (RESULTS / "comparisons.json").write_text(json.dumps({k: with_pct(v) for k, v in comparisons.items()}, indent=1))
    stats["runtime_s"] = round(time.time() - t0, 1)
    stats["config"] = {"seeds": list(SEEDS), "deadlines_h": list(DEADLINES_H), "delta": DELTA,
                       "held_out": HELD_OUT, "calibration": CALIBRATION,
                       "primary": asdict(Scenario("deferral", PRIMARY_H, "neso", DELTA, theta)) | {"fallback": "fail_open"}}
    (RESULTS / "data_stats.json").write_text(json.dumps(stats, indent=1, default=str))

    from figures import make_all  # noqa: PLC0415
    from make_tables import main as make_tables  # noqa: PLC0415
    make_all(RESULTS, FIGDIR)
    make_tables()
    print(json.dumps(verdict, indent=2))
    print(f"done in {time.time() - t0:.1f}s")


def capacity_experiment(rates: np.ndarray, actual: np.ndarray, nat: dict, cum: np.ndarray, n_slots: int) -> list[dict]:
    """Scale x1 and x100 with a per-slot start cap sized to the calibration-month peak of immediate deployment."""
    sig = Signals(score=actual, forecasts={"neso": nat["forecast"]})
    k_max = int(PRIMARY_H * 60 / SLOT_MIN)
    cal_hi = int(MONTHS[0][2] // SLOT_MIN)
    rows = []
    for scale in SCALES:
        for seed in SEEDS:
            wl = workload.simulate(rates * scale, seed)
            s_of = (wl.arrival_min // SLOT_MIN).astype(int)
            cap = int(np.bincount(s_of[s_of < cal_hi], minlength=cal_hi).max())
            runs = {
                ("immediate", True): capacity_start_times("immediate", wl, nat["forecast"], k_max, DELTA, cap, n_slots),
                ("deferral", True): capacity_start_times("deferral", wl, nat["forecast"], k_max, DELTA, cap, n_slots),
                ("deferral", False): start_times(Scenario("deferral", PRIMARY_H, "neso", DELTA), wl, sig,
                                                 np.random.default_rng(seed))[0],
            }
            for (pol, capped), start in runs.items():
                st = (start // SLOT_MIN).astype(int)
                fb = np.zeros(len(start), bool)
                sc = Scenario(pol, PRIMARY_H, "neso", DELTA)
                for label, lo, hi in MONTHS:
                    m = month_metrics(sc, wl, start, fb, sig, cum, lo, hi)
                    sel = (wl.arrival_min >= lo) & (wl.arrival_min < hi)
                    peak = np.bincount(st[sel]).max() if sel.any() else 0
                    rows.append({"experiment": "capacity", "scale": scale, "policy": pol, "capped": capped,
                                 "max_delay_h": PRIMARY_H, "cap": cap, "seed": seed, "month": label,
                                 "peak_ratio": peak / cap, **m})
    return rows


if __name__ == "__main__":
    main()
