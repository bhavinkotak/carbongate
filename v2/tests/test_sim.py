import numpy as np

from carbongate import workload
from carbongate.gate import Fallback
from carbongate.sim import (SLOT_MIN, Scenario, Signals, _start_times_loop, capacity_start_times, cumulative,
                            emissions_g, last_ok_slot, month_metrics, outage_mask, persistence, slot_offsets,
                            start_times)
from carbongate.stats import t_ci

N = 48 * 30


def synthetic(seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(N)
    actual = 150 + 80 * np.sin(2 * np.pi * t / 48) + rng.normal(0, 15, N)
    forecast = actual + rng.normal(0, 10, N)
    forecast[rng.random(N) < 0.02] = np.nan
    return actual, forecast


def wl_for(n=N, seed=0, rate=1.0, urgent=0.1):
    return workload.simulate(np.full(n - 40, rate), seed, urgent_fraction=urgent)


def test_emissions_constant_intensity():
    e = emissions_g(np.array([10.0]), np.array([45.0]), np.array([2.0]), np.full(10, 100.0))
    assert np.isclose(e[0], 200.0)


def test_emissions_cross_slot_average():
    inten = np.array([100.0, 300.0, 300.0])
    e = emissions_g(np.array([20.0]), np.array([20.0]), np.array([1.0]), inten)
    assert np.isclose(e[0], (10 * 100 + 10 * 300) / 20)


def test_persistence_is_causal():
    a = np.arange(200.0)
    p = persistence(a)
    assert np.isnan(p[:48]).all() and np.array_equal(p[48:], a[:-48])


def test_vectorised_matches_gate_loop():
    actual, forecast = synthetic()
    wl = wl_for()
    sig = Signals(score=actual, forecasts={"neso": forecast}, persistence_source=actual)
    for pol, theta in (("deferral", np.inf), ("threshold", 150.0)):
        sc = Scenario(pol, 4, "neso", 0.05, theta)
        v, _ = start_times(sc, wl, sig, np.random.default_rng(0))
        loop, _ = _start_times_loop(sc, wl, forecast, sig, np.random.default_rng(0))
        assert np.allclose(v, loop)


def test_no_sla_violation_without_outages():
    actual, forecast = synthetic()
    wl = wl_for()
    sig = Signals(score=actual, forecasts={"neso": forecast})
    for pol in ("threshold", "deferral", "oracle"):
        for h in (2, 4, 8):
            start, _ = start_times(Scenario(pol, h, "neso", 0.05, 120.0), wl, sig, np.random.default_rng(0))
            delay = start - wl.arrival_min
            assert delay.min() >= 0 and delay.max() <= h * 60 + 1e-9
            assert np.all(delay[wl.urgent] == 0)


def test_decisions_do_not_read_actuals():
    actual, forecast = synthetic()
    wl = wl_for()
    sc = Scenario("deferral", 4, "neso", 0.05)
    s1, _ = start_times(sc, wl, Signals(score=actual, forecasts={"neso": forecast}), np.random.default_rng(0))
    s2, _ = start_times(sc, wl, Signals(score=actual[::-1].copy(), forecasts={"neso": forecast}),
                        np.random.default_rng(0))
    assert np.array_equal(s1, s2)


def test_oracle_start_slot_is_optimal():
    actual, forecast = synthetic()
    sc_o, sc_f = Scenario("oracle", 4), Scenario("deferral", 4, "neso", 0.0)
    o = slot_offsets(sc_o, actual)
    f = slot_offsets(sc_f, forecast)
    idx = np.arange(N - 10)
    assert np.all(actual[idx + o[idx]] <= actual[idx + f[idx]] + 1e-9)


def test_reduction_invariant_to_energy_scale():
    actual, forecast = synthetic()
    wl = wl_for()
    sig = Signals(score=actual, forecasts={"neso": forecast})
    sc = Scenario("deferral", 4, "neso", 0.05)
    start, fb = start_times(sc, wl, sig, np.random.default_rng(0))
    cum = cumulative(actual)
    r1 = month_metrics(sc, wl, start, fb, sig, cum, 0, 1e9)["reduction"]
    wl2 = workload.Workload(wl.arrival_min, wl.duration_min, wl.energy_kwh * 7.3, wl.urgent)
    r2 = month_metrics(sc, wl2, start, fb, sig, cum, 0, 1e9)["reduction"]
    assert np.isclose(r1, r2) and r1 > 0


def test_outage_mask_fraction_and_cache_freshness():
    m = outage_mask(200_000, 0.2, np.random.default_rng(1))
    assert abs(m.mean() - 0.2) < 0.02
    fresh = last_ok_slot(np.array([False, True, True, False]))
    assert list(fresh) == [0, 0, 0, 3]


def test_fail_closed_violates_and_fail_open_does_not():
    actual, forecast = synthetic()
    wl = wl_for()
    sig = Signals(score=actual, forecasts={"neso": forecast}, persistence_source=actual)
    res = {}
    for fb in Fallback:
        sc = Scenario("deferral", 2, "neso", 0.05, outage_frac=0.5, fallback=fb)
        start, used = start_times(sc, wl, sig, np.random.default_rng(3))
        res[fb] = (start - wl.arrival_min > 120 + 1e-9).sum(), used.mean()
    assert res[Fallback.FAIL_OPEN][0] == 0 and res[Fallback.CACHED][0] == 0
    assert res[Fallback.FAIL_CLOSED][0] > 0
    assert all(v[1] > 0 for v in res.values())


def test_capacity_never_exceeded_and_large_cap_matches_uncapped():
    actual, forecast = synthetic()
    wl = wl_for(rate=3.0)
    start = capacity_start_times("deferral", wl, forecast, 8, 0.05, 4, N - 40)
    assert np.bincount((start // SLOT_MIN).astype(int)).max() <= 4
    big = capacity_start_times("deferral", wl, forecast, 8, 0.05, 10**6, N - 40)
    ref, _ = start_times(Scenario("deferral", 4, "neso", 0.05), wl,
                         Signals(score=actual, forecasts={"neso": forecast}), np.random.default_rng(0))
    assert np.allclose(big, ref)


def test_workload_urgent_fraction_and_energy():
    wl = workload.simulate(np.full(20_000, 2.0), 0)
    assert abs(wl.urgent.mean() - workload.URGENT_FRACTION) < 0.01
    assert (wl.energy_kwh > 0).all() and wl.duration_min.max() <= workload.DURATION_MAX_MIN


def test_t_ci_contains_mean():
    m, sd, lo, hi = t_ci(np.array([0.1, 0.2, 0.3]))
    assert lo < m < hi and np.isclose(m, 0.2) and np.isclose(sd, 0.1)
