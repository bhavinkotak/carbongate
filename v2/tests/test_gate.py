import numpy as np
import pytest

from carbongate.gate import Action, Fallback, Response, Status, decide, deferral_offset


def ok(*vals):
    return Response(Status.OK, np.array(vals, float))


def test_urgent_bypasses_everything():
    d = decide("deferral", urgent=True, remaining=8, resp=Response(Status.TIMEOUT), fallback=Fallback.FAIL_CLOSED)
    assert d.action is Action.DEPLOY_NOW and d.reason == "urgent_bypass"


def test_immediate_never_waits():
    assert decide("immediate", urgent=False, remaining=8, resp=ok(500, 1)).action is Action.DEPLOY_NOW


def test_deferral_picks_earliest_minimum():
    d = decide("deferral", urgent=False, remaining=4, resp=ok(200, 150, 100, 100, 180))
    assert (d.action, d.offset) == (Action.DEFER, 2)


def test_deferral_respects_margin():
    assert deferral_offset(np.array([100, 97.0]), 0.05) == 0
    assert deferral_offset(np.array([100, 94.0]), 0.05) == 1


def test_deferral_truncates_to_remaining_sla():
    d = decide("deferral", urgent=False, remaining=1, resp=ok(200, 190, 10))
    assert d.offset == 1


def test_missing_future_slot_is_not_a_candidate():
    d = decide("deferral", urgent=False, remaining=3, resp=ok(200, np.nan, 150, np.nan))
    assert d.offset == 2


@pytest.mark.parametrize("status", [Status.TIMEOUT, Status.MISSING])
def test_fallback_modes(status):
    resp = Response(status) if status is Status.TIMEOUT else ok(np.nan, 100)
    assert decide("deferral", urgent=False, remaining=4, resp=resp).action is Action.DEPLOY_NOW
    d = decide("deferral", urgent=False, remaining=4, resp=resp, fallback=Fallback.FAIL_CLOSED)
    assert d.action is Action.HOLD and d.fallback_used
    d = decide("deferral", urgent=False, remaining=4, resp=resp, fallback=Fallback.CACHED,
               cached=np.array([300, 100, 200.0]))
    assert (d.action, d.offset, d.fallback_used) == (Action.DEFER, 1, True)
    d = decide("deferral", urgent=False, remaining=4, resp=resp, fallback=Fallback.CACHED,
               cached=np.array([np.nan, 100.0]))
    assert d.action is Action.DEPLOY_NOW and d.reason == "cache_empty_fail_open"


def test_threshold_gate():
    assert decide("threshold", urgent=False, remaining=3, resp=ok(90), theta=100).action is Action.DEPLOY_NOW
    assert decide("threshold", urgent=False, remaining=3, resp=ok(190), theta=100).action is Action.HOLD
    assert decide("threshold", urgent=False, remaining=0, resp=ok(190), theta=100).action is Action.DEPLOY_NOW


def test_fail_closed_threshold_holds_even_at_deadline():
    d = decide("threshold", urgent=False, remaining=0, resp=Response(Status.TIMEOUT), theta=100,
               fallback=Fallback.FAIL_CLOSED)
    assert d.action is Action.HOLD


def test_unknown_policy():
    with pytest.raises(ValueError):
        decide("magic", urgent=False, remaining=1, resp=ok(1, 2))
