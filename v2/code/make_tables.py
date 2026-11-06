"""Render the LaTeX table bodies used in paper/main.tex directly from results/ (copied verbatim into the paper)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"


def pct(x: float, nd: int = 2) -> str:
    s = f"{100 * x:.{nd}f}"
    if float(s) == 0:
        return f"{0:.{nd}f}"
    return s.replace("-", "$-$") if s.startswith("-") else s


def ci(r: dict) -> str:
    return f"[{pct(r['reduction_ci_lo'])}, {pct(r['reduction_ci_hi'])}]"


def find(rows: list[dict], **kw) -> dict:
    hits = [r for r in rows if all(r.get(k) == v for k, v in kw.items())]
    assert len(hits) == 1, (kw, len(hits))
    return hits[0]


def main_table(s: list[dict]) -> str:
    names = {"threshold": "Static threshold", "deferral": "CarbonGate-F", "oracle": "Oracle"}
    out = []
    for h in (2, 4, 8):
        for p in ("threshold", "deferral", "oracle"):
            r = find(s, experiment="main", policy=p, max_delay_h=h)
            out.append(f"{h} & {names[p]} & {pct(r['reduction_mean'])} & {pct(r['reduction_std_months'])} & {ci(r)} & "
                       f"{r['delay_p50_min']:.1f} & {r['delay_p95_min']:.1f} & {pct(r['deferral_rate'], 1)} & "
                       f"{pct(r['harmful_deferral_rate'], 1)} \\\\")
        out.append("\\midrule" if h != 8 else "")
    return "\n".join(x for x in out if x)


def ablation_table(s: list[dict]) -> str:
    rows = [("Forecast", "NESO forecast (primary)", find(s, experiment="main", policy="deferral", max_delay_h=4))]
    rows += [("Forecast", "Day-ahead persistence", find(s, experiment="forecaster", forecaster="persistence"))]
    for sg in (10, 25, 50):
        rows.append(("Forecast", f"NESO + noise, $\\sigma={sg}$", find(s, experiment="forecaster",
                                                                      forecaster=f"neso+noise{sg}")))
    for d in (0.0, 0.10, 0.20):
        rows.append(("Margin", f"$\\delta={d:.2f}$", find(s, experiment="delta", delta=d)))
    for u in (0.0, 0.30):
        rows.append(("Urgent", f"$p_u={u:.2f}$", find(s, experiment="urgent", urgent_fraction=u, policy="deferral")))
    rows.append(("Arrivals", "Uniform 24/7", find(s, experiment="shape", policy="deferral")))
    rows.append(("Arrivals", "Uniform 24/7, oracle", find(s, experiment="shape", policy="oracle")))
    return "\n".join(f"{g} & {n} & {pct(r['reduction_mean'])} & {ci(r)} & {r['delay_p50_min']:.1f} & "
                     f"{pct(r['deferral_rate'], 1)} & {pct(r['harmful_deferral_rate'], 1)} \\\\" for g, n, r in rows)


def fallback_table(s: list[dict]) -> str:
    scen = [((0.05, 0.0), "Outage 5\\%"), ((0.20, 0.0), "Outage 20\\%"), ((0.50, 0.0), "Outage 50\\%"),
            ((0.0, 0.10), "Timeout 10\\%")]
    fbs = [("fail_open", "Fail-open"), ("fail_closed", "Fail-closed"), ("cached_persistence", "Cached")]
    out = []
    for (of, tp), sname in scen:
        for j, (fb, fname) in enumerate(fbs):
            cells = []
            for pol in ("deferral", "threshold"):
                r = find(s, experiment="fallback", policy=pol, fallback=fb, outage_frac=of, timeout_prob=tp)
                cells += [pct(r["reduction_mean"]), pct(r["sla_violation_rate"]), f"{r['delay_max_min']:.0f}"]
            lead = sname if j == 0 else ""
            out.append(f"{lead} & {fname} & {pct(find(s, experiment='fallback', policy='deferral', fallback=fb, outage_frac=of, timeout_prob=tp)['fallback_rate'], 1)} & "
                       + " & ".join(cells) + " \\\\")
        out.append("\\midrule")
    return "\n".join(out[:-1])


def region_table(s: list[dict], stats: dict) -> str:
    out = []
    for reg in ("GB national", "North Scotland", "North West England", "South Wales", "East England", "London"):
        d = find(s, experiment="region", region=reg, policy="deferral")
        o = find(s, experiment="region", region=reg, policy="oracle")
        mean_i = stats["held_out_actual_mean"] if reg == "GB national" else stats["regional_mean_forecast"][reg]
        out.append(f"{reg} & {mean_i:.1f} & {pct(d['reduction_mean'])} {ci(d)} & {pct(o['reduction_mean'])} & "
                   f"{d['saved_kg_per_seed']:.3f} & {d['base_kg_per_seed']:.2f} & {d['n_months']} \\\\")
    return "\n".join(out)


def capacity_table(c: list[dict]) -> str:
    out = []
    for r in c:
        pol = "Immediate" if r["policy"] == "immediate" else "CarbonGate-F"
        cap = "yes" if r["capped"] else "no"
        out.append(f"$\\times${r['scale']} & {pol} & {cap} & {r['peak_ratio']:.2f} & {pct(r['reduction_mean'])} {ci(r)} & "
                   f"{r['delay_p50_min']:.1f} & {r['delay_p95_min']:.1f} \\\\")
    return "\n".join(out)


def main() -> None:
    s = json.loads((RES / "summary.json").read_text())
    c = json.loads((RES / "capacity_summary.json").read_text())
    st = json.loads((RES / "data_stats.json").read_text())
    text = "\n\n".join([f"% main\n{main_table(s)}", f"% ablation\n{ablation_table(s)}",
                        f"% fallback\n{fallback_table(s)}", f"% region\n{region_table(s, st)}",
                        f"% capacity\n{capacity_table(c)}"])
    (ROOT / "paper" / "generated_tables.tex").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
