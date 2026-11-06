"""Trace-driven replay of deployment policies against the GB carbon-intensity record."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .gate import Action, Fallback, Response, Status, decide
from .workload import Workload

SLOT_MIN = 30
DAY_SLOTS = 48
OUTAGE_MEAN_SLOTS = 4  # mean outage episode length (2 h) for injected forecaster outages


@dataclass(frozen=True)
class Scenario:
    policy: str  # immediate | threshold | deferral | oracle
    max_delay_h: float = 4.0
    forecaster: str = "neso"
    delta: float = 0.05
    theta: float = float("inf")
    outage_frac: float = 0.0
    timeout_prob: float = 0.0
    fallback: Fallback = Fallback.FAIL_OPEN

    @property
    def k_max(self) -> int:
        return int(round(self.max_delay_h * 60 / SLOT_MIN))

    @property
    def injected(self) -> bool:
        return self.outage_frac > 0 or self.timeout_prob > 0 or self.fallback is not Fallback.FAIL_OPEN


@dataclass
class Signals:
    """Decision-side forecasts (may contain NaN) and the scoring signal (gap-free)."""
    score: np.ndarray
    forecasts: dict[str, np.ndarray] = field(default_factory=dict)
    persistence_source: np.ndarray | None = None  # raw realised series used to build the cached fallback


def persistence(raw_actual: np.ndarray) -> np.ndarray:
    """Day-ahead persistence: the forecast for slot u is the realised value at u - 48 (causal for leads < 24 h)."""
    out = np.full_like(raw_actual, np.nan)
    out[DAY_SLOTS:] = raw_actual[:-DAY_SLOTS]
    return out


def cumulative(intensity: np.ndarray) -> np.ndarray:
    return np.concatenate([[0.0], np.cumsum(intensity * SLOT_MIN)])


def _integral(t: np.ndarray, intensity: np.ndarray, cum: np.ndarray) -> np.ndarray:
    s = np.minimum((t // SLOT_MIN).astype(int), len(intensity) - 1)
    return cum[s] + intensity[s] * (t - s * SLOT_MIN)


def emissions_g(start_min: np.ndarray, dur_min: np.ndarray, energy_kwh: np.ndarray, intensity: np.ndarray,
                cum: np.ndarray | None = None) -> np.ndarray:
    """Eq. (emissions): energy times the time-averaged intensity over the deployment interval (gCO2)."""
    cum = cumulative(intensity) if cum is None else cum
    mean_i = (_integral(start_min + dur_min, intensity, cum) - _integral(start_min, intensity, cum)) / dur_min
    return energy_kwh * mean_i


def _windows(x: np.ndarray, k: int) -> np.ndarray:
    return sliding_window_view(np.concatenate([x, np.full(k, np.nan)]), k + 1)[: len(x)]


def slot_offsets(sc: Scenario, decision_signal: np.ndarray) -> np.ndarray:
    """Vectorised decision per arrival slot when the forecaster never fails (natural nulls fail open)."""
    w = _windows(decision_signal, sc.k_max)
    if sc.policy == "immediate":
        return np.zeros(len(w), dtype=int)
    if sc.policy in ("deferral", "oracle"):
        delta = 0.0 if sc.policy == "oracle" else sc.delta
        wi = np.where(np.isnan(w), np.inf, w)
        k = np.argmin(wi, axis=1)
        best = wi[np.arange(len(w)), k]
        ok = (k > 0) & (best <= (1 - delta) * wi[:, 0]) & ~np.isnan(w[:, 0])
        return np.where(ok, k, 0)
    if sc.policy == "threshold":
        hit = (w <= sc.theta) | np.isnan(w)
        hit[:, -1] = True
        return np.argmax(hit, axis=1)
    raise ValueError(sc.policy)


def outage_mask(n: int, frac: float, rng: np.random.Generator) -> np.ndarray:
    """Alternating renewal process: geometric outage episodes covering about `frac` of slots."""
    mask = np.zeros(n, dtype=bool)
    if frac <= 0:
        return mask
    mean_up = OUTAGE_MEAN_SLOTS * (1 - frac) / frac
    i, down = int(rng.geometric(1 / mean_up)), True
    while i < n:
        length = int(rng.geometric(1 / OUTAGE_MEAN_SLOTS)) if down else int(rng.geometric(1 / mean_up))
        if down:
            mask[i:i + length] = True
        i += length
        down = not down
    return mask


def last_ok_slot(mask: np.ndarray) -> np.ndarray:
    """For each slot, the most recent slot at which the API was reachable (cache freshness)."""
    idx = np.where(~mask, np.arange(len(mask)), -1)
    return np.maximum.accumulate(idx)


def decision_signal(sc: Scenario, sig: Signals) -> np.ndarray:
    return sig.score if sc.policy == "oracle" else sig.forecasts[sc.forecaster]


def start_times(sc: Scenario, wl: Workload, sig: Signals, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Return (start minute, fallback-used flag) per deployment."""
    a = wl.arrival_min
    s = (a // SLOT_MIN).astype(int)
    dec = decision_signal(sc, sig)
    if not sc.injected or sc.policy in ("immediate", "oracle"):
        off = slot_offsets(sc, dec)[s]
        off = np.where(wl.urgent, 0, off)
        start = np.where(off == 0, a, (s + off) * SLOT_MIN).astype(float)
        gated = sc.policy not in ("immediate", "oracle")
        fb = ~wl.urgent & np.isnan(dec[np.minimum(s + off, len(dec) - 1)]) if gated else np.zeros(len(a), bool)
        return start, fb
    return _start_times_loop(sc, wl, dec, sig, rng)


def _start_times_loop(sc: Scenario, wl: Workload, dec: np.ndarray, sig: Signals,
                      rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    n = len(dec)
    down = outage_mask(n, sc.outage_frac, rng)
    fresh = last_ok_slot(down)
    src = sig.persistence_source
    a = wl.arrival_min
    start, fb = a.astype(float).copy(), np.zeros(len(a), dtype=bool)
    k = sc.k_max
    for i in np.argsort(a, kind="stable"):
        if wl.urgent[i]:
            continue
        s0, j = int(a[i] // SLOT_MIN), 0
        while True:
            u = s0 + j
            if u >= n - 1:
                start[i] = u * SLOT_MIN
                break
            remaining = k - j
            hi = min(n, u + max(remaining, 0) + 1)
            status = Status.TIMEOUT if (down[u] or rng.random() < sc.timeout_prob) else Status.OK
            cached = None
            if sc.fallback is Fallback.CACHED and src is not None:
                lags = np.arange(u, hi) - DAY_SLOTS
                cached = np.where((lags >= 0) & (lags < fresh[u]), src[np.clip(lags, 0, n - 1)], np.nan)
            d = decide(sc.policy, urgent=False, remaining=remaining,
                       resp=Response(status, dec[u:hi] if status is Status.OK else None),
                       delta=sc.delta, theta=sc.theta, fallback=sc.fallback, cached=cached)
            fb[i] |= d.fallback_used
            if d.action is Action.DEPLOY_NOW:
                start[i] = a[i] if j == 0 else u * SLOT_MIN
                break
            if d.action is Action.DEFER:
                start[i] = (u + d.offset) * SLOT_MIN
                break
            j += 1
    return start, fb


def month_metrics(sc: Scenario, wl: Workload, start: np.ndarray, fb: np.ndarray, sig: Signals,
                  cum: np.ndarray, lo_min: float, hi_min: float) -> dict[str, float]:
    sel = (wl.arrival_min >= lo_min) & (wl.arrival_min < hi_min)
    a, d, e, urg = wl.arrival_min[sel], wl.duration_min[sel], wl.energy_kwh[sel], wl.urgent[sel]
    base = emissions_g(a, d, e, sig.score, cum)
    pol = emissions_g(start[sel], d, e, sig.score, cum)
    delay = start[sel] - a
    nu = delay[~urg]
    deferred = delay > 1e-9
    harmful = float((pol[deferred] > base[deferred] + 1e-12).mean()) if deferred.any() else 0.0
    base, pol = base.sum(), pol.sum()
    return {
        "n_deploy": int(sel.sum()), "n_urgent": int(urg.sum()),
        "base_kg": base / 1000, "policy_kg": pol / 1000, "saved_kg": (base - pol) / 1000,
        "reduction": 1 - pol / base if base > 0 else float("nan"),
        "harmful_deferral_rate": harmful,
        "delay_mean_min": float(nu.mean()) if len(nu) else 0.0,
        "delay_p50_min": float(np.percentile(nu, 50)) if len(nu) else 0.0,
        "delay_p95_min": float(np.percentile(nu, 95)) if len(nu) else 0.0,
        "delay_max_min": float(nu.max()) if len(nu) else 0.0,
        "deferral_rate": float((nu > 1e-9).mean()) if len(nu) else 0.0,
        "sla_violations": int((delay > sc.max_delay_h * 60 + 1e-6).sum()),
        "fallback_rate": float(fb[sel][~urg].mean()) if len(nu) else 0.0,
        "bypass_rate": float(urg.mean()),
    }


def capacity_start_times(policy: str, wl: Workload, dec: np.ndarray, k_max: int, delta: float,
                         cap: int, n_slots: int) -> np.ndarray:
    """Online per-slot allocation with at most `cap` deployment starts per slot (reservations are binding).

    Urgent deployments (and every deployment under `immediate`) take the earliest free slot; deferrable ones
    fill the forecast-ranked slots of their SLA window first and spill past the deadline only if all are full.
    """
    a = wl.arrival_min
    s_of = (a // SLOT_MIN).astype(int)
    order = np.lexsort((a, s_of))
    used = np.zeros(n_slots + 8 * k_max + 4096, dtype=int)
    start = a.astype(float).copy()
    bounds = np.searchsorted(s_of[order], np.arange(n_slots + 1))

    def place(s: int, ids: np.ndarray, ks: list[int]) -> None:
        p, ks_iter = 0, iter(ks)
        while p < len(ids):
            kk = next(ks_iter, None)
            if kk is None:  # preference list exhausted: continue past it in time order
                kk = max(ks) + 1 if ks else 0
                ks = [*ks, kk]
                ks_iter = iter([])
            free = cap - used[s + kk]
            if free <= 0:
                continue
            take = min(free, len(ids) - p)
            used[s + kk] += take
            chunk = ids[p:p + take]
            start[chunk] = a[chunk] if kk == 0 else (s + kk) * SLOT_MIN
            p += take

    for s in range(n_slots):
        idx = order[bounds[s]:bounds[s + 1]]
        if len(idx) == 0:
            continue
        win = dec[s:s + k_max + 1]
        urg = idx[wl.urgent[idx]] if policy == "deferral" else idx
        rest = idx[~wl.urgent[idx]] if policy == "deferral" else idx[:0]
        place(s, urg, [0])
        if len(rest):
            if not np.isnan(win[0]):
                wi = np.where(np.isnan(win), np.inf, win)
                better = [int(k) for k in np.argsort(wi, kind="stable") if k > 0 and wi[k] <= (1 - delta) * wi[0]]
            else:
                better = []
            pref = better + [0] + [k for k in range(1, len(win)) if k not in better]
            place(s, rest, pref)
    return start
