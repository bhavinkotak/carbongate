"""SIMULATED deployment workload and declared per-deployment energy model.

All power coefficients below are ASSUMPTIONS carried over from the v1 CarbonGate estimator; they are not
measured. The primary endpoint (relative reduction) does not depend on them because per-deployment energy
is drawn independently of start time (see paper, Eq. eq:reduction).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

LONDON = ZoneInfo("Europe/London")

# Arrival model (SIMULATED)
WORK_START_H = 9
WORK_END_H = 18
RATE_WORK_PER_H = 4.0
RATE_OFF_PER_H = 0.25
URGENT_FRACTION = 0.10

# Energy model (ASSUMED coefficients, v1 estimator defaults)
CPU_WATTS_PER_CORE = 10.0
MEM_WATTS_PER_GB = 0.375
PUE = 1.4
CORE_CHOICES = (0.5, 1.0, 2.0, 4.0)
CORE_PROBS = (0.2, 0.4, 0.3, 0.1)
MEM_GB_PER_CORE = 2.0
DURATION_MEDIAN_MIN = 15.0
DURATION_SIGMA = 0.5
DURATION_MIN_MIN = 3.0
DURATION_MAX_MIN = 60.0


@dataclass(frozen=True)
class Workload:
    arrival_min: np.ndarray  # minutes since the record start (UTC)
    duration_min: np.ndarray
    energy_kwh: np.ndarray
    urgent: np.ndarray  # bool

    def __len__(self) -> int:
        return len(self.arrival_min)


def slot_rates(slots: list[datetime], shape: str = "working_hours", scale: float = 1.0) -> np.ndarray:
    """Expected arrivals per 30-minute slot."""
    if shape == "uniform":
        daily = 5 * (RATE_WORK_PER_H * (WORK_END_H - WORK_START_H) + RATE_OFF_PER_H * (24 - WORK_END_H + WORK_START_H))
        daily += 2 * RATE_OFF_PER_H * 24
        return np.full(len(slots), scale * daily / 7 / 48)
    rates = np.empty(len(slots))
    for i, t in enumerate(slots):
        loc = t.astimezone(LONDON)
        work = loc.weekday() < 5 and WORK_START_H <= loc.hour < WORK_END_H
        rates[i] = (RATE_WORK_PER_H if work else RATE_OFF_PER_H) / 2
    return scale * rates


def energy_kwh(cores: np.ndarray, duration_min: np.ndarray) -> np.ndarray:
    watts = cores * CPU_WATTS_PER_CORE + cores * MEM_GB_PER_CORE * MEM_WATTS_PER_GB
    return PUE * watts * duration_min / 60.0 / 1000.0


def simulate(rates: np.ndarray, seed: int, urgent_fraction: float = URGENT_FRACTION,
             slot_minutes: int = 30) -> Workload:
    rng = np.random.default_rng(seed)
    counts = rng.poisson(rates)
    slot_of = np.repeat(np.arange(len(rates)), counts)
    arrival = slot_of * slot_minutes + rng.uniform(0, slot_minutes, size=len(slot_of))
    dur = np.clip(rng.lognormal(np.log(DURATION_MEDIAN_MIN), DURATION_SIGMA, size=len(slot_of)),
                  DURATION_MIN_MIN, DURATION_MAX_MIN)
    cores = rng.choice(CORE_CHOICES, p=CORE_PROBS, size=len(slot_of))
    urgent = rng.random(len(slot_of)) < urgent_fraction
    return Workload(arrival, dur, energy_kwh(cores, dur), urgent)
