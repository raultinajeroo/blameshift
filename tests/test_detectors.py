"""Detection behavior: the four claims in the module docstring, plus more."""

from __future__ import annotations

import numpy as np
import pytest

from blameshift import SeriesPoint, detect_change_points

START = 1_767_657_600.0  # fixed epoch; only relative spacing matters


def make_points(values, *, start: float = START, step: float = 300.0) -> list[SeriesPoint]:
    return [
        SeriesPoint(timestamp=start + i * step, value=float(v))
        for i, v in enumerate(values)
    ]


def test_planted_regression_detected_within_two_samples():
    rng = np.random.default_rng(0)
    values = 200.0 + rng.normal(0.0, 4.0, size=300)
    true_index = 180
    values[true_index:] *= 1.15

    cps = detect_change_points(make_points(values))

    assert len(cps) == 1
    cp = cps[0]
    assert abs(cp.index - true_index) <= 2
    assert cp.direction == "regression"
    assert cp.effect_ms == pytest.approx(30.0, abs=4.0)
    assert cp.effect_pct == pytest.approx(15.0, abs=2.0)
    assert 0.0 < cp.confidence <= 1.0
    assert cp.timestamp == pytest.approx(START + cp.index * 300.0)


def test_stable_series_has_no_change_points():
    rng = np.random.default_rng(1)
    values = 200.0 + rng.normal(0.0, 4.0, size=200)

    assert detect_change_points(make_points(values)) == []


def test_single_spike_is_not_a_change_point():
    rng = np.random.default_rng(2)
    values = 200.0 + rng.normal(0.0, 4.0, size=200)
    values[100] = 500.0  # one bad sample, 2.5x baseline

    assert detect_change_points(make_points(values)) == []


def test_improvement_shift_detected_with_direction():
    rng = np.random.default_rng(3)
    values = 200.0 + rng.normal(0.0, 4.0, size=300)
    true_index = 150
    values[true_index:] *= 0.85

    cps = detect_change_points(make_points(values))

    assert len(cps) == 1
    assert abs(cps[0].index - true_index) <= 2
    assert cps[0].direction == "improvement"
    assert cps[0].effect_ms < 0
    assert cps[0].effect_pct == pytest.approx(-15.0, abs=2.0)


def test_seasonal_stationary_noise_has_no_change_points():
    rng = np.random.default_rng(4)
    t = np.arange(400, dtype=float)
    values = 200.0 + 3.0 * np.sin(2.0 * np.pi * t / 288.0) + rng.normal(0.0, 4.0, size=400)

    assert detect_change_points(make_points(values)) == []


def test_short_series_returns_nothing():
    rng = np.random.default_rng(5)
    values = 200.0 + rng.normal(0.0, 4.0, size=30)  # < 2 * window

    assert detect_change_points(make_points(values)) == []


def test_invalid_parameters_rejected():
    points = make_points([200.0] * 100)
    with pytest.raises(ValueError):
        detect_change_points(points, window=1)
    with pytest.raises(ValueError):
        detect_change_points(points, z_threshold=0)
    with pytest.raises(ValueError):
        detect_change_points(points, min_run=0)


def test_two_distinct_shifts_both_detected():
    rng = np.random.default_rng(6)
    values = 200.0 + rng.normal(0.0, 4.0, size=400)
    values[120:] *= 1.15
    values[300:] *= 1.15  # second, later regression

    cps = detect_change_points(make_points(values))

    assert len(cps) == 2
    assert abs(cps[0].index - 120) <= 2
    assert abs(cps[1].index - 300) <= 2
    assert all(cp.direction == "regression" for cp in cps)
