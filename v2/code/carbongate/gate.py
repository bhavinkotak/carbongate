"""CarbonGate admission decision: a pure function from (deployment, forecast response) to an action.

The same function backs the GitHub-check / admission-webhook integration points described in the paper and
the trace-driven simulator. It never reads actual (realised) intensity unless the policy is the oracle.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class Status(Enum):
    OK = "ok"
    MISSING = "missing"  # API answered but the current-slot value is null/absent (unknown result)
    TIMEOUT = "timeout"  # no answer within the client timeout budget, or the API is down


class Fallback(Enum):
    FAIL_OPEN = "fail_open"  # deploy now, record that the gate was bypassed
    FAIL_CLOSED = "fail_closed"  # hold and re-query next slot; never deploy unchecked
    CACHED = "cached_persistence"  # decide on cached day-ahead persistence; fail open if the cache is empty


class Action(Enum):
    DEPLOY_NOW = "deploy_now"
    DEFER = "defer"  # start at the beginning of slot (now + offset)
    HOLD = "hold"  # re-evaluate at the next slot


@dataclass(frozen=True)
class Response:
    status: Status
    window: np.ndarray | None = None  # forecast for slots now..now+k_max (NaN = missing slot)


@dataclass(frozen=True)
class Decision:
    action: Action
    offset: int = 0
    reason: str = ""
    fallback_used: bool = False


def classify(resp: Response) -> Status:
    """A response whose current-slot value is missing is treated as an unknown result."""
    if resp.status is Status.OK and (resp.window is None or len(resp.window) == 0 or np.isnan(resp.window[0])):
        return Status.MISSING
    return resp.status


def deferral_offset(window: np.ndarray, delta: float) -> int:
    """Eq. (deferral rule): earliest argmin over non-missing slots, only if it beats now by a factor (1 - delta)."""
    w = np.where(np.isnan(window), np.inf, window)
    k = int(np.argmin(w))
    return k if k > 0 and w[k] <= (1.0 - delta) * w[0] else 0


def threshold_ok(window: np.ndarray, theta: float) -> bool:
    return bool(window[0] <= theta)


def decide(policy: str, *, urgent: bool, remaining: int, resp: Response, delta: float = 0.05,
           theta: float = float("inf"), fallback: Fallback = Fallback.FAIL_OPEN,
           cached: np.ndarray | None = None) -> Decision:
    """remaining = number of slot offsets still allowed by the SLA (0 means the deadline is the current slot)."""
    if urgent:
        return Decision(Action.DEPLOY_NOW, reason="urgent_bypass")
    if policy == "immediate":
        return Decision(Action.DEPLOY_NOW, reason="baseline")
    status, window, used = classify(resp), resp.window, False
    if status is not Status.OK:
        if fallback is Fallback.FAIL_OPEN:
            return Decision(Action.DEPLOY_NOW, reason=f"fail_open_{status.value}", fallback_used=True)
        if fallback is Fallback.FAIL_CLOSED:
            return Decision(Action.HOLD, reason=f"fail_closed_{status.value}", fallback_used=True)
        if cached is None or len(cached) == 0 or np.isnan(cached[0]):
            return Decision(Action.DEPLOY_NOW, reason="cache_empty_fail_open", fallback_used=True)
        window, used = cached, True
    window = window[: max(remaining, 0) + 1]
    if policy in ("deferral", "oracle"):
        k = deferral_offset(window, 0.0 if policy == "oracle" else delta)
        if k == 0:
            return Decision(Action.DEPLOY_NOW, reason="now_is_best", fallback_used=used)
        return Decision(Action.DEFER, offset=k, reason="defer_to_min", fallback_used=used)
    if policy == "threshold":
        if threshold_ok(window, theta) or remaining <= 0:
            return Decision(Action.DEPLOY_NOW, reason="below_threshold_or_deadline", fallback_used=used)
        return Decision(Action.HOLD, reason="above_threshold", fallback_used=used)
    raise ValueError(f"unknown policy {policy}")
