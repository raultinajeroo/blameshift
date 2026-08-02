"""Synthetic demo data: a latency series with one planted regression.

The generator is fully deterministic for a given seed. It produces a
plausible-looking p95 latency series (200ms baseline, light daily
seasonality, gaussian noise) with exactly one +15% level shift, plus a
change log in which one deploy lands shortly before the shift and several
decoy events are scattered far from it (or after it, where a correct blame
window must not look).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .series import ChangeEvent, SeriesPoint

#: Fixed series start so a given (points, seed) pair is fully reproducible.
SERIES_START = datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp()
SAMPLE_INTERVAL_S = 300.0  # one sample every 5 minutes

CULPRIT_ID = "deploy-482"
CULPRIT_LEAD_S = 37.0 * 60.0  # culprit lands 37 minutes before the shift
REGRESSION_FACTOR = 1.15
BASELINE_MS = 200.0


@dataclass(frozen=True)
class SimulationResult:
    points: list[SeriesPoint]
    events: list[ChangeEvent]
    planted_index: int
    planted_event_id: str
    shift_pct: float


def generate(points: int = 400, seed: int = 7) -> SimulationResult:
    """Generate a synthetic series with one planted regression."""
    if points < 60:
        raise ValueError("points must be >= 60 to fit the demo scenario")

    rng = np.random.default_rng(seed)
    n = points
    t = np.arange(n, dtype=float)

    # Baseline: mild daily seasonality (period = 1 day of 5-min samples)
    # plus noise. Seasonal amplitude is small enough that the detector at
    # default thresholds stays silent on it.
    seasonal = 3.0 * np.sin(2.0 * np.pi * t / 288.0)
    noise = rng.normal(0.0, 4.0, size=n)
    values = BASELINE_MS + seasonal + noise

    planted_index = int(n * 0.6)
    values[planted_index:] *= REGRESSION_FACTOR

    timestamps = SERIES_START + t * SAMPLE_INTERVAL_S
    series = [
        SeriesPoint(timestamp=float(ts), value=float(v))
        for ts, v in zip(timestamps, values)
    ]

    cp_time = float(timestamps[planted_index])
    events = [
        ChangeEvent(
            id="deploy-471",
            timestamp=cp_time - 6.0 * 86400.0,
            kind="deploy",
            title="roll out cart service v2.3",
            author="mara.osei",
        ),
        ChangeEvent(
            id="commit-9c1f2d",
            timestamp=cp_time - 3.0 * 86400.0,
            kind="commit",
            title="refactor session cache keys",
            author="jonas.berg",
        ),
        ChangeEvent(
            id="deploy-479",
            timestamp=cp_time - 30.0 * 3600.0,
            kind="deploy",
            title="enable new recommendation model (shadow)",
            author="priya.nair",
        ),
        ChangeEvent(
            id=CULPRIT_ID,
            timestamp=cp_time - CULPRIT_LEAD_S,
            kind="deploy",
            title="switch checkout to new inventory client",
            author="alex.kim",
        ),
        ChangeEvent(
            id="config-114",
            timestamp=cp_time + 2.0 * 86400.0,
            kind="config",
            title="raise connection pool ceiling",
            author="alex.kim",
        ),
    ]
    events.sort(key=lambda e: e.timestamp)

    return SimulationResult(
        points=series,
        events=events,
        planted_index=planted_index,
        planted_event_id=CULPRIT_ID,
        shift_pct=(REGRESSION_FACTOR - 1.0) * 100.0,
    )


def _iso(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def write_demo(result: SimulationResult, out_dir: str | Path) -> tuple[Path, Path, Path]:
    """Write series.csv, changes.json, and the ground-truth answer key."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    series_path = out / "series.csv"
    lines = ["timestamp,value"]
    lines += [f"{_iso(p.timestamp)},{p.value:.4f}" for p in result.points]
    series_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    changes_path = out / "changes.json"
    changes_payload = {
        "changes": [
            {
                "id": e.id,
                "timestamp": _iso(e.timestamp),
                "kind": e.kind,
                "title": e.title,
                "author": e.author,
            }
            for e in result.events
        ]
    }
    changes_path.write_text(
        json.dumps(changes_payload, indent=2) + "\n", encoding="utf-8"
    )

    truth_path = out / "truth.json"
    truth_payload = {
        "planted_index": result.planted_index,
        "planted_time_utc": _iso(result.points[result.planted_index].timestamp),
        "planted_event_id": result.planted_event_id,
        "shift_pct": result.shift_pct,
        "note": "answer key for the synthetic demo; not used by `blameshift run`",
    }
    truth_path.write_text(json.dumps(truth_payload, indent=2) + "\n", encoding="utf-8")

    return series_path, changes_path, truth_path
