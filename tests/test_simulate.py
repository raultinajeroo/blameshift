"""Simulator: determinism, file formats, and the planted-regression contract."""

from __future__ import annotations

import json

import pytest

from blameshift import (
    attribute,
    detect_change_points,
    generate,
    load_changes_json,
    load_series_csv,
    write_demo,
)


def test_generate_is_deterministic():
    a = generate(points=400, seed=7)
    b = generate(points=400, seed=7)
    c = generate(points=400, seed=8)

    assert [p.value for p in a.points] == [p.value for p in b.points]
    assert [e.id for e in a.events] == [e.id for e in b.events]
    assert [p.value for p in a.points] != [p.value for p in c.points]


def test_planted_regression_is_found_and_blamed(tmp_path):
    result = generate(points=400, seed=7)
    series_path, changes_path, _ = write_demo(result, tmp_path)

    points = load_series_csv(series_path)
    events = load_changes_json(changes_path)
    cps = detect_change_points(points)

    assert len(cps) == 1
    cp = cps[0]
    assert abs(cp.index - result.planted_index) <= 2
    assert cp.direction == "regression"
    assert cp.effect_pct == pytest.approx(result.shift_pct, abs=2.0)

    (attr,) = attribute(cps, events)
    assert attr.top_suspect is not None
    assert attr.top_suspect.event.id == result.planted_event_id
    # The in-window decoy is ranked strictly lower.
    suspect_ids = [s.event.id for s in attr.suspects]
    assert suspect_ids.index(result.planted_event_id) < suspect_ids.index("deploy-479")
    # Decoys outside the lookback window are never even candidates.
    assert "deploy-471" not in suspect_ids
    assert "commit-9c1f2d" not in suspect_ids
    # The post-shift config change must not be blamed for its own past.
    assert "config-114" not in suspect_ids


def test_write_demo_file_formats(tmp_path):
    result = generate(points=120, seed=11)
    series_path, changes_path, truth_path = write_demo(result, tmp_path)

    header, first_row, *_ = series_path.read_text().splitlines()
    assert header == "timestamp,value"
    ts_text, value_text = first_row.split(",")
    assert "T" in ts_text  # ISO-8601 timestamp
    assert float(value_text) > 0

    payload = json.loads(changes_path.read_text())
    assert isinstance(payload["changes"], list)
    assert {"id", "timestamp", "kind", "title", "author"} <= set(
        payload["changes"][0]
    )

    truth = json.loads(truth_path.read_text())
    assert truth["planted_event_id"] == result.planted_event_id
    assert truth["planted_index"] == result.planted_index

    # Round-trip through the loaders preserves ordering and count.
    assert len(load_series_csv(series_path)) == 120
    events = load_changes_json(changes_path)
    assert len(events) == len(result.events)
    assert events == sorted(events, key=lambda e: e.timestamp)


def test_generate_rejects_tiny_series():
    with pytest.raises(ValueError):
        generate(points=10, seed=7)
