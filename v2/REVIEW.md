# REVIEW: green-gitops (CarbonGate) v1 to v2

Hostile-reviewer grill of v1 ("Carbon-Aware GitOps: Implementing Energy-Efficient Quality Gates in Kubernetes
Delivery Workflows", Zenodo 10.5281/zenodo.18527247), followed by the v1 claim audit, v1 scores, and v2 re-score.

## Round 1: Frontier (assumptions, prerequisites, baselines)

- **Average vs marginal intensity.** v1 multiplies energy by grid *average* intensity. Shifting load changes the
  *marginal* generator, not the average mix. GB has no free marginal series. Action: v2 scores on NESO average
  ("actual") intensity, names it a proxy, and lists marginal accounting as an untested threat.
- **Deferrability.** v1 assumes most deploys can wait hours. Hotfixes, security patches, and release trains cannot.
  Action: 10% urgent deploys bypass the gate in the main grid; urgent share ablated (0, 10%, 30%).
- **What energy moves.** Deferring a deploy shifts only the pipeline/rollout transient, not the service's
  steady-state energy. v1 implied cluster-scale savings. Action: v2 reports absolute kg alongside percentages.
- **Per-deploy energy model.** v1 coefficients (10 W/core, 0.375 W/GB, PUE 1.4) are unsourced. Action: declared as
  assumptions in code; v2 shows the relative endpoint is invariant to energy scale (Eq. reduction, unit test).
- **Forecast vintage (leakage risk).** The API "forecast" for past slots is the final, short-lead forecast, not the
  forecast available hours ahead. Action: decisions use only the forecast field; ablations add a strictly causal
  day-ahead persistence forecaster and Gaussian forecast noise (10/25/50 gCO2/kWh); oracle uses actuals.
- **Prerequisites.** v1 used WattTime and Electricity Maps (keys, licences). v2 uses the free NESO API (CC BY 4.0),
  raw JSON cached with sha256.
- **Baselines a reviewer demands.** Let's Wait Awhile style forecast deferral (implemented: CarbonGate-F is this
  rule placed at the delivery gate), static threshold gate (implemented), oracle (implemented), Google CICS (not
  reproducible: proprietary capacity curves; recorded as unavailable), WattTime marginal shifting (no GB data;
  recorded as unavailable).

## Round 2: Breakpoints

| Breakpoint | v2 handling |
|---|---|
| Forecaster outage | Injected outage episodes covering 5/20/50% of slots; fail-open, fail-closed, cached-persistence fallbacks (tested, Fig. fallback, Table fallback). |
| Forecaster timeout | Independent per-query timeout probability 10%; same three fallbacks. Live latency probe of the forward-forecast endpoint (20 calls) against a 2 s budget. |
| Missing values / unknown result | Null current-slot value is treated as an unknown result and routed to the fallback; null future slots are excluded from the argmin (unit tests). |
| Forecast error | Persistence and noise ablations; harmful-deferral rate (deferrals that raised emissions) reported. |
| Urgent hotfixes | Bypass path; bypass rate reported; urgent share ablation. |
| Regions without data | Regions with no forecast fall back like an outage; region heterogeneity tested on 5 GB regions (proxy scoring). Non-GB grids untested (threat). |
| Scale x100 | x100 arrivals with a per-slot start cap equal to the calibration-month peak of immediate deployment; herding (peak ratio), spill delay, and SLA violations measured. |
| Grid feedback at scale | Not modelled (deploy energy is tiny relative to grid); threat. |

## Round 3: Defensibility

- **Right metric?** Relative reduction of *average-intensity-weighted* deploy energy is a proxy. It ignores
  marginal effects, embodied carbon, and the gate's own overhead. Stated as a proxy in the paper.
- **Falsifier.** Preregistered: H1 refuted if the upper 95% CI bound of mean held-out reduction (4 h SLA) is below
  5%, or any SLA violation occurs. H2 tests v1's 23% lower bound.
- **Measurement bias.** Workload is simulated (arrival shape drives the result; uniform-arrival ablation included).
  The forecast field is optimistic (short lead); persistence gives a pessimistic bound. Months are the unit of
  replication (n = 11 held-out), seeds only vary the simulated workload.

## v1 claim audit

| v1 claim | Status | v2 action |
|---|---|---|
| "191,240 production deployments", "500 production deployments", 3 clouds, 50 services, 6 months | No data, internally inconsistent (500 vs 191,240) | Removed; replaced by a labelled trace-driven simulation on 12 months of real GB grid data |
| "23-31% reduction"; per-region table (23.1/28.5/31.4%) | No data; Discussion contradicts it (EU 31% vs APAC 18%) | Removed; H2 tests the 23% bound with measured values |
| "zero increase in deployment latency" / "<30 s overhead, p=0.23" | No data; contradicts "median delay 2.5 h" | Reframed: added delay p50/p95 per SLA measured; live API latency probed |
| "92% developer acceptance", survey of 156 developers | No data | Removed; stated as untested |
| "0.6% false positive rate (1,147 blocked)" | No data | Removed; fallback behaviour measured under injected outages |
| "1,769 kg CO2 saved, $88 credit value, ROI positive" | No data | Removed; absolute kg per simulated year reported |
| Intro statistics (3% of electricity, 83% lack metrics, 67% GitOps adoption, CSRD 50,000 companies, 15-25 kW clusters, "carbon costs vary 10x", "60% of deployments could be scheduled") | Uncited or cited to unverifiable sources | Removed |
| Caspian 33%, CarbonScaler 51% | Mis-cited (wrong authors/venues/years for CarbonScaler, Kepler, NPAKS) | Removed numbers; CarbonScaler and Kepler cited to verified DOIs |
| Refs [2],[4],[5],[6],[8],[12],[14],[16] | Unverifiable or wrong metadata (e.g. arXiv:2405.13858 and 2504.10702 do not match titles) | Dropped; every v2 reference has a verified DOI/arXiv id or is software with URL only |
| "first standard metric", "proven framework", "ESG-compliant", "production viability" | Overclaims | Removed |
| Open-source repo and Zenodo dataset links | github.com/bhavinkotak/carbongate returns HTTP 200 but holds v1 code; the dataset URL is not a Zenodo record | Repo kept only as a related identifier; v2 code and data ship in the Zenodo package |

## v1 scores (desk criteria)

C1 3/10 (hype: seamless, production-ready, first standard) | C2 1/10 (fabricated/mis-attributed refs) | C3 3/10
(unnumbered equations, undefined alpha/T_min interplay) | C4 2/10 (one line on "fallback to historical averages") |
C5 1/10 (no denominators, no seeds/CIs) | C6 2/10 (500 vs 191,240; 23-31% vs 18%; zero latency vs 2.5 h) | C7 4/10 |
C8 1/10 | C9 1/10 | C10 2/10 | C11 0/10 (no preregistration).
Soundness 2, Novelty 4, Clarity 5, Reproducibility 1. Weighted = 0.6*2 + 0.4*4 = 2.8 -> reject.

## v2 outcome

- Preregistration written before the bulk download (`preregistration.json`); verdicts in `results/verdict.json`.
- **H1 (>= 5% reduction, 4 h SLA, zero violations): INCONCLUSIVE.** Mean 4.80%, 95% CI [4.17, 5.43]% over
  11 held-out months x 5 seeds; numerator 0.369 kg, denominator 7.52 kg CO2 per seed; 0 SLA violations.
- **H2 (v1 claim >= 23%): REFUTED.**
- Negative results reported: static threshold gate (v1 design) is <= 0 at 2 h and 4 h; noise sigma 50 makes deferral
  harmful; x100 load with a capacity cap removes the gain (herding); fail-closed breaks SLAs under outages.
- Abstract and conclusion avoid confirms/proves/validates/demonstrates/establishes for H1.

## v2 re-score (self-assessed, hostile stance)

| Criterion | Score | Note |
|---|---|---|
| C1 | 9 | No filler/hype, no em-dashes; short sentences. |
| C2 | 9 | 21 DOI/arXiv refs verified against Crossref/arXiv; 5 software/API refs URL-only with no attributed numbers. |
| C3 | 9 | 9 numbered, labelled equations (system model, objective, constraints, rules, fallback, metric). |
| C4 | 9 | Missing/timeout/outage outcomes specified (Eq. fallback) and tested; live latency probe. |
| C5 | 8 | Numerators/denominators, 11 months x 5 seeds, t-CIs, paired Wilcoxon, ablations. n = 11 is small. |
| C6 | 9 | Tables generated by `code/make_tables.py` from results and checked line-by-line against main.tex. |
| C7 | 10 | All figures, tables, equations, algorithm labelled and referenced. |
| C8 | 9 | Workload labelled SIMULATED; regional scoring labelled proxy; average-intensity metric labelled proxy. |
| C9 | 10 | Desk check numeric grounding passes (488 numbers checked). |
| C10 | 9 | Threats list marginal emissions, forecast vintage, simulated workload, GB only, no live controller, CICS/WattTime unavailable, developer acceptance untested, herding fix untested. |
| C11 | 10 | Preregistered; verdict computed in code; inconclusive/refuted reported honestly. |

Soundness 7, Novelty 5, Clarity 8, Reproducibility 9. Weighted = 0.6*7 + 0.4*5 = 6.2.
Honest reading: sound and reproducible, but novelty is modest (an LWA-style rule placed at the GitOps gate) and the
primary result is inconclusive, so a TOSEM/TKDE-level accept (>= 7.0) is unlikely without live-controller data,
more grids, or a capacity-aware release policy. As a corrected preprint it is defensible.

## Final desk-check output

```
Desk check: .../zenodo-v2/green-gitops/paper/main.tex  sections=['Introduction', 'Related Work', 'Methodology',
'Evaluation', 'Threats to Validity', 'Conclusion', 'Acknowledgment', 'Changes from Version 1']
abstract_words=237  method_eqs=9  numbers_checked=488
PASS
```
(all 21 DOI/arXiv references: `verify ...: ok`; pytest: 24 passed)
