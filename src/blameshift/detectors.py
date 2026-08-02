"""Change-point detection for latency series.

The detector is a robust two-window scan with a CUSUM confirmation step.
It is deliberately conservative: it fires on sustained level shifts and is
designed to ignore single-point spikes and stationary noise.

Algorithm
---------
1. **Two-window scan.** Slide a split point ``i`` through the series with
   ``window`` (n, default 25) samples on each side. Compute
   ``median_before = median(x[i-n:i])`` and ``median_after = median(x[i:i+n])``.
   The scale estimate is a *pooled MAD*: the median of the absolute
   deviations of both halves from their own medians, multiplied by the
   usual consistency constant 1.4826 so it estimates sigma (not
   0.6745 * sigma) for near-gaussian noise. The robust z-score is

       z = (median_after - median_before) / (1.4826 * pooled_MAD * sqrt(2/n) + eps)

   where ``sqrt(2/n)`` scales the difference of two independent medians and
   ``eps`` is a small data-scaled constant that keeps the denominator
   positive. A split is a *candidate* when ``|z| >= z_threshold``
   (default 6.0).

2. **Persistence check.** A candidate only survives if the shift persists:
   at least ``min_run`` (default 10) of the ``n`` samples after the split
   must lie on the shifted side of ``median_before``. This is what rejects
   spikes — a single outlier moves neither the median nor the run count.

3. **CUSUM confirmation.** From the split onward, accumulate
   ``cusum_j = sum(x[i:j] - median_before)``. A true level shift pushes the
   cumulative sum monotonically away from zero; the candidate is confirmed
   only if the extreme CUSUM value within the after-window exceeds
   ``k * pooled_MAD`` (k default 8) in the direction of the shift. Noise
   wanders back; a level shift does not.

4. **Merge and localize.** One real shift produces a contiguous band of
   candidates about ``window`` wide, symmetric around the true boundary
   (the band opens when the after-window becomes majority post-shift and
   closes when the before-window does). Candidates within ``n/2`` of each
   other are chain-merged into one cluster, and the change point is placed
   at the cluster center, whose split statistics are re-evaluated directly.
   The center is a far more accurate boundary estimate than the argmax of
   ``|z|``: the z numerator plateaus across the band while its MAD
   denominator fluctuates with noise, so argmax-|z| wanders several samples
   off the true shift. If the center unexpectedly fails the checks, the
   candidate with the largest ``|z|`` is kept instead. Clusters narrower
   than ``window / 2`` splits are discarded outright: a genuine level shift
   always produces a band about ``window`` wide, while an isolated noise
   crossing of the z threshold produces only a handful of adjacent
   candidates. (Observed: 24-26 wide for a real shift, 1-8 wide for noise
   false positives.)

Each surviving change point reports its index, timestamp, direction
(``regression`` when latency went up, ``improvement`` when it went down),
the effect in ms and percent, and a confidence in [0, 1] computed as the
saturating map ``|z| / (|z| + z_threshold)`` (0.5 at the threshold,
approaching 1 for very strong shifts).

Limits: this detects abrupt level shifts, not gradual drift, and it needs at
least two windows of data (``2 * window`` samples) to say anything at all.
Strongly seasonal series can produce marginal false positives near the
threshold (confidence ~0.5); deseasonalize first if that matters.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .series import SeriesPoint

_MAD_CONSISTENCY = 1.4826  # makes MAD a consistent estimator of sigma


@dataclass(frozen=True)
class ChangePoint:
    """A detected, confirmed level shift in the latency series."""

    index: int                    # index of the first post-shift sample
    timestamp: float              # epoch seconds of that sample
    direction: str                # "regression" | "improvement"
    effect_ms: float              # median_after - median_before
    effect_pct: float             # effect relative to median_before, in %
    confidence: float             # in [0, 1]
    z: float                      # robust z-score of the shift
    median_before: float          # ms
    median_after: float           # ms
    persist_count: int            # post-shift samples on the shifted side
    window: int                   # n, the scan window used
    cusum_extreme: float          # confirming CUSUM extreme, in ms*samples
    extras: dict = field(default_factory=dict, compare=False)

    @property
    def persistence(self) -> float:
        """Fraction of the post-change window still on the shifted side."""
        return self.persist_count / self.window


@dataclass(frozen=True)
class _SplitStats:
    z: float
    mad: float
    median_before: float
    median_after: float
    persist_count: int
    cusum_extreme: float


def _split_stats(
    values: np.ndarray, i: int, window: int, eps: float
) -> _SplitStats:
    """All scan statistics for a split after sample ``i - 1``."""
    before = values[i - window : i]
    after = values[i : i + window]
    median_before = float(np.median(before))
    median_after = float(np.median(after))
    dev = np.concatenate([np.abs(before - median_before),
                          np.abs(after - median_after)])
    mad = float(np.median(dev))
    z = (median_after - median_before) / (
        _MAD_CONSISTENCY * mad * np.sqrt(2.0 / window) + eps
    )
    sign = 1.0 if z >= 0 else -1.0
    persist_count = int(np.count_nonzero(sign * (after - median_before) > 0))
    cusum_extreme = float(np.max(np.cumsum(sign * (after - median_before))))
    return _SplitStats(
        z=float(z),
        mad=mad,
        median_before=median_before,
        median_after=median_after,
        persist_count=persist_count,
        cusum_extreme=cusum_extreme,
    )


def _passes(stats: _SplitStats, z_threshold: float, min_run: int, k: float) -> bool:
    return (
        abs(stats.z) >= z_threshold
        and stats.persist_count >= min_run
        and stats.cusum_extreme > k * stats.mad
    )


def _to_change_point(
    stats: _SplitStats,
    index: int,
    points: list[SeriesPoint],
    window: int,
    z_threshold: float,
) -> ChangePoint:
    effect_ms = stats.median_after - stats.median_before
    effect_pct = (
        100.0 * effect_ms / stats.median_before
        if stats.median_before != 0
        else float("inf")
    )
    return ChangePoint(
        index=index,
        timestamp=points[index].timestamp,
        direction="regression" if stats.z > 0 else "improvement",
        effect_ms=effect_ms,
        effect_pct=effect_pct,
        confidence=abs(stats.z) / (abs(stats.z) + z_threshold),
        z=stats.z,
        median_before=stats.median_before,
        median_after=stats.median_after,
        persist_count=stats.persist_count,
        window=window,
        cusum_extreme=stats.cusum_extreme,
    )


def detect_change_points(
    points: list[SeriesPoint],
    *,
    window: int = 25,
    z_threshold: float = 6.0,
    min_run: int = 10,
    k: float = 8.0,
) -> list[ChangePoint]:
    """Detect level shifts in ``points``.

    Parameters mirror the algorithm description in the module docstring.
    Returns change points ordered by index. A stable or noisy-but-stationary
    series yields an empty list at the default thresholds.
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    if min_run < 1 or min_run > window:
        raise ValueError("min_run must be in [1, window]")
    if z_threshold <= 0:
        raise ValueError("z_threshold must be > 0")
    if k <= 0:
        raise ValueError("k must be > 0")

    values = np.array([p.value for p in points], dtype=float)
    n_total = len(values)
    if n_total < 2 * window:
        return []

    # Data-scaled epsilon: irrelevant next to any real MAD, but keeps the
    # denominator positive for a perfectly flat series.
    eps = 1e-9 * (float(np.median(np.abs(values))) + 1.0)

    stats_at = {
        i: _split_stats(values, i, window, eps)
        for i in range(window, n_total - window + 1)
    }
    candidate_indices = [
        i
        for i, stats in stats_at.items()
        if _passes(stats, z_threshold, min_run, k)
    ]
    if not candidate_indices:
        return []

    change_points: list[ChangePoint] = []
    for cluster in _cluster(candidate_indices, merge_distance=window // 2):
        # A real level shift yields a band about `window` wide; a lone
        # noise crossing yields a narrow cluster. Discard narrow clusters.
        if len(cluster) < window // 2:
            continue
        center = int(round((cluster[0] + cluster[-1]) / 2))
        center_stats = stats_at.get(center) or _split_stats(values, center, window, eps)
        if _passes(center_stats, z_threshold, min_run, k):
            change_points.append(
                _to_change_point(center_stats, center, points, window, z_threshold)
            )
        else:
            # Defensive fallback: keep the strongest raw candidate.
            best = max(cluster, key=lambda i: abs(stats_at[i].z))
            change_points.append(
                _to_change_point(stats_at[best], best, points, window, z_threshold)
            )
    return change_points


def _cluster(indices: list[int], *, merge_distance: int) -> list[list[int]]:
    """Group sorted indices into chains with gaps of at most ``merge_distance``."""
    clusters = [[indices[0]]]
    for i in indices[1:]:
        if i - clusters[-1][-1] <= merge_distance:
            clusters[-1].append(i)
        else:
            clusters.append([i])
    return clusters
