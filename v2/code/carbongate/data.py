"""Download, cache, and parse the NESO Carbon Intensity API record (GB, 30-minute slots).

Raw responses are cached verbatim (gzip) under data/raw so reruns are offline and reproducible.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

API_BASE = "https://api.carbonintensity.org.uk"
NATIONAL_URL = API_BASE + "/intensity/{start}/{end}"
REGIONAL_URL = API_BASE + "/regional/intensity/{start}/{end}"
PROBE_URL = API_BASE + "/intensity/{start}/fw24h"
LICENSE = "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/); terms: https://github.com/carbon-intensity/terms"

START = datetime(2025, 11, 1, tzinfo=UTC)
END = datetime(2026, 11, 2, tzinfo=UTC)  # one day past the last evaluated month so deferred starts stay in-record
SLOT_MINUTES = 30
SLOT = timedelta(minutes=SLOT_MINUTES)
MAX_DAYS_PER_CALL = 14  # API limit for /intensity/{from}/{to}
CHUNK_DAYS = 13  # stay below the limit; the regional endpoint rejects full 14-day ranges
REQUEST_SLEEP_S = 1.0
REGIONS = {1: "North Scotland", 3: "North West England", 7: "South Wales", 10: "East England", 13: "London"}
PROBE_CALLS = 20
GATE_TIMEOUT_S = 2.0  # client timeout budget used by the gate for a forecast query


def stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%MZ")


def parse_stamp(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)


def _get(url: str, timeout: float = 120.0) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": "carbongate-v2-research (zenodo reproduction)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https host
        return resp.read()


def chunks(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    out, cur = [], start
    while cur < end:
        nxt = min(cur + timedelta(days=CHUNK_DAYS), end)
        out.append((cur, nxt))
        cur = nxt
    return out


def fetch_all(raw_dir: Path, kind: str) -> list[Path]:
    """Fetch national or regional chunks, skipping any already cached."""
    template = NATIONAL_URL if kind == "national" else REGIONAL_URL
    raw_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for a, b in chunks(START, END):
        path = raw_dir / f"{kind}_{a:%Y%m%d}_{b:%Y%m%d}.json.gz"
        if not path.exists():
            body = _get(template.format(start=stamp(a), end=stamp(b)))
            if "data" not in json.loads(body):
                raise RuntimeError(f"API error for {kind} {a}: {body[:200]!r}")
            path.write_bytes(gzip.compress(body, mtime=0))
            time.sleep(REQUEST_SLEEP_S)
        paths.append(path)
    return paths


def slot_index() -> list[datetime]:
    n = int((END - START) / SLOT)
    return [START + i * SLOT for i in range(n)]


def load_national(paths: list[Path]) -> dict[str, np.ndarray]:
    """Return forecast and actual arrays (NaN where missing) aligned to slot_index()."""
    n = int((END - START) / SLOT)
    fc, ac = np.full(n, np.nan), np.full(n, np.nan)
    for p in paths:
        for row in json.loads(gzip.decompress(p.read_bytes()))["data"]:
            i = int((parse_stamp(row["from"]) - START) / SLOT)
            if 0 <= i < n:
                f, a = row["intensity"].get("forecast"), row["intensity"].get("actual")
                fc[i] = np.nan if f is None else float(f)
                ac[i] = np.nan if a is None else float(a)
    return {"forecast": fc, "actual": ac}


def load_regional(paths: list[Path]) -> dict[int, np.ndarray]:
    n = int((END - START) / SLOT)
    out = {rid: np.full(n, np.nan) for rid in REGIONS}
    for p in paths:
        for row in json.loads(gzip.decompress(p.read_bytes()))["data"]:
            i = int((parse_stamp(row["from"]) - START) / SLOT)
            if not 0 <= i < n:
                continue
            for r in row["regions"]:
                if r["regionid"] in out and r["intensity"].get("forecast") is not None:
                    out[r["regionid"]][i] = float(r["intensity"]["forecast"])
    return out


def clean_national_actual(actual: np.ndarray) -> tuple[np.ndarray, int]:
    """A national actual of exactly 0 gCO2/kWh is treated as a missing value (reporting glitch)."""
    bad = actual == 0
    out = actual.copy()
    out[bad] = np.nan
    return out, int(bad.sum())


def interpolate_gaps(x: np.ndarray) -> tuple[np.ndarray, int]:
    """Linear interpolation of NaN slots for scoring only; returns the filled array and gap count."""
    bad = np.isnan(x)
    if not bad.any():
        return x.copy(), 0
    idx = np.arange(len(x))
    y = x.copy()
    y[bad] = np.interp(idx[bad], idx[~bad], x[~bad])
    return y, int(bad.sum())


def latency_probe(raw_dir: Path) -> Path:
    """Time PROBE_CALLS sequential calls to the forward-forecast endpoint a live gate would use (cached)."""
    path = raw_dir / "latency_probe.json"
    if path.exists():
        return path
    samples = []
    for _ in range(PROBE_CALLS):
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        t0 = time.perf_counter()
        try:
            body = _get(PROBE_URL.format(start=stamp(now)), timeout=30)
            ok = "data" in json.loads(body)
        except Exception:  # noqa: BLE001 - a failed probe is a data point
            ok = False
        samples.append({"seconds": time.perf_counter() - t0, "ok": ok})
        time.sleep(REQUEST_SLEEP_S)
    path.write_text(json.dumps({"endpoint": PROBE_URL, "retrieved_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                                "samples": samples}, indent=1))
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_sources(data_dir: Path, national: list[Path], regional: list[Path], probe: Path) -> None:
    lines = ["# Data sources", "",
             "All files in `raw/` are verbatim API responses (gzip-compressed JSON), cached by `code/run_all.py`.", "",
             f"- Provider: National Energy System Operator (NESO), Carbon Intensity API for Great Britain",
             f"- Documentation: https://carbon-intensity.github.io/api-definitions/",
             f"- National endpoint: `{NATIONAL_URL}` (fields: forecast, actual; gCO2/kWh; 30-minute slots)",
             f"- Regional endpoint: `{REGIONAL_URL}` (field: forecast only)",
             f"- Latency probe endpoint: `{PROBE_URL}`",
             f"- License: {LICENSE}. Attribution: Carbon Intensity API, NESO.",
             f"- Period: {stamp(START)} to {stamp(END)} (UTC), {CHUNK_DAYS}-day request chunks",
             "", "| file | retrieved (UTC, file mtime) | sha256 |", "|---|---|---|"]
    for p in [*national, *regional, probe]:
        mtime = datetime.fromtimestamp(p.stat().st_mtime, UTC).strftime("%Y-%m-%d")
        lines.append(f"| raw/{p.name} | {mtime} | `{sha256(p)}` |")
    (data_dir / "SOURCES.md").write_text("\n".join(lines) + "\n")
