"""Blame attribution: map detected change points to suspect change events.

For each *regression* change point at time ``t`` we consider every recorded
:class:`~blameshift.series.ChangeEvent` in the window
``[t - lookback, t]`` (lookback default 48h) and rank them by

    score = w1 * exp(-dt / tau)          # temporal proximity, tau default 6h
          + w2 * normalized_effect       # shift size, capped at a 50% shift
          + w3 * persistence             # fraction of the post-change window
                                         # still on the shifted side

with default weights ``(w1, w2, w3) = (0.5, 0.3, 0.2)``. Temporal proximity
is the dominant term: an effect term shared by every candidate cannot
discriminate between them, but it does scale the score with how consequential
the regression is. Improvement change points are reported but not blamed —
nothing "caused" an improvement worth hunting.

Attribution is honest about the empty case: if no change was recorded in the
window, the result says so instead of pointing at a distant event.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .detectors import ChangePoint
from .series import ChangeEvent

#: Default score weights (temporal proximity, effect size, persistence).
DEFAULT_WEIGHTS = (0.5, 0.3, 0.2)

#: Effect size, in percent, that maps to a normalized effect of 1.0.
EFFECT_CAP_PCT = 50.0


@dataclass(frozen=True)
class Suspect:
    """One ranked change event with its score breakdown."""

    event: ChangeEvent
    dt_seconds: float          # change point time minus event time (>= 0)
    score: float
    temporal_score: float
    effect_score: float
    persistence_score: float


@dataclass(frozen=True)
class EvidenceCard:
    """Human-readable explanation of why a suspect was blamed."""

    change_id: str
    kind: str
    title: str
    author: str
    dt_seconds: float
    median_before: float
    median_after: float
    effect_ms: float
    effect_pct: float
    persist_count: int
    window: int
    score: float
    temporal_score: float
    effect_score: float
    persistence_score: float
    confidence: float
    rationale: str


@dataclass(frozen=True)
class Attribution:
    """The blame result for one change point."""

    change_point: ChangePoint
    suspects: list[Suspect] = field(default_factory=list)
    card: EvidenceCard | None = None
    unattributed_reason: str | None = None

    @property
    def top_suspect(self) -> Suspect | None:
        return self.suspects[0] if self.suspects else None


def format_duration(seconds: float) -> str:
    """Human duration such as '37 minutes' or '5.2 hours'."""
    minutes = seconds / 60.0
    if minutes < 90:
        n = int(round(minutes))
        return f"{n} minute{'s' if n != 1 else ''}"
    hours = seconds / 3600.0
    if hours < 48:
        return f"{hours:.1f} hours"
    return f"{hours / 24.0:.1f} days"


def _build_rationale(
    event: ChangeEvent, cp: ChangePoint, dt_seconds: float, score: float,
    unit: str = "ms",
) -> str:
    sign = "+" if cp.effect_ms >= 0 else "-"
    persisted_all = cp.persist_count == cp.window
    persistence_clause = (
        f"persisted across all {cp.persist_count} subsequent samples"
        if persisted_all
        else f"persisted across {cp.persist_count} of {cp.window} "
        "subsequent samples"
    )
    before = f"{cp.median_before:.0f}ms" if unit == "ms" else format_value(cp.median_before, unit)
    after = f"{cp.median_after:.0f}ms" if unit == "ms" else format_value(cp.median_after, unit)
    explanation = (
        f"Blame score {score:.2f}: temporal proximity dominates because the "
        "change landed inside the lookback window closest to the shift."
        if unit == "ms" else
        f"Event score {score:.2f}: this is a temporal association, not evidence of causality."
    )
    return (
        f"{event.kind} {event.id} (\"{event.title}\", by {event.author}) "
        f"landed {format_duration(dt_seconds)} before a {sign}{abs(cp.effect_pct):.1f}% "
        f"median shift ({before} -> {after}) "
        f"that {persistence_clause}. "
        f"{explanation}"
    )


def format_value(value: float, unit: str = "ms", *, signed: bool = False) -> str:
    """Keep small probability changes visible without changing latency output."""
    precision = 1 if unit == "ms" else 4
    sign = "+" if signed else ""
    return f"{value:{sign}.{precision}f}{unit}"


def attribute(
    change_points: list[ChangePoint],
    events: list[ChangeEvent],
    *,
    lookback_hours: float = 48.0,
    tau_hours: float = 6.0,
    weights: tuple[float, float, float] = DEFAULT_WEIGHTS,
    unit: str = "ms",
) -> list[Attribution]:
    """Rank events for regressions and neutral increase/decrease change points.

    Returns one :class:`Attribution` per change point, in input order.
    Regressions with no events in the lookback window are marked
    ``unattributed``; latency improvements carry no suspects at all.
    Probability-mode increases and decreases both receive event rankings.
    """
    if tau_hours <= 0:
        raise ValueError("tau_hours must be > 0")
    if lookback_hours <= 0:
        raise ValueError("lookback_hours must be > 0")
    w1, w2, w3 = weights
    if min(weights) < 0 or not math.isclose(sum(weights), 1.0, abs_tol=1e-6):
        raise ValueError("weights must be non-negative and sum to 1.0")

    lookback_s = lookback_hours * 3600.0
    tau_s = tau_hours * 3600.0

    attributions: list[Attribution] = []
    for cp in change_points:
        if cp.direction not in ("regression", "increase", "decrease"):
            attributions.append(Attribution(change_point=cp))
            continue

        window_events = [
            e for e in events if cp.timestamp - lookback_s <= e.timestamp <= cp.timestamp
        ]
        if not window_events:
            attributions.append(
                Attribution(
                    change_point=cp,
                    unattributed_reason=(
                        f"unattributed — no recorded changes in the "
                        f"{lookback_hours:g}h window before the shift"
                    ),
                )
            )
            continue

        normalized_effect = min(abs(cp.effect_pct) / EFFECT_CAP_PCT, 1.0)
        suspects: list[Suspect] = []
        for event in window_events:
            dt = cp.timestamp - event.timestamp
            temporal = math.exp(-dt / tau_s)
            score = (
                w1 * temporal
                + w2 * normalized_effect
                + w3 * cp.persistence
            )
            suspects.append(
                Suspect(
                    event=event,
                    dt_seconds=dt,
                    score=score,
                    temporal_score=w1 * temporal,
                    effect_score=w2 * normalized_effect,
                    persistence_score=w3 * cp.persistence,
                )
            )
        suspects.sort(key=lambda s: (-s.score, s.dt_seconds, s.event.id))

        top = suspects[0]
        card = EvidenceCard(
            change_id=top.event.id,
            kind=top.event.kind,
            title=top.event.title,
            author=top.event.author,
            dt_seconds=top.dt_seconds,
            median_before=cp.median_before,
            median_after=cp.median_after,
            effect_ms=cp.effect_ms,
            effect_pct=cp.effect_pct,
            persist_count=cp.persist_count,
            window=cp.window,
            score=top.score,
            temporal_score=top.temporal_score,
            effect_score=top.effect_score,
            persistence_score=top.persistence_score,
            confidence=cp.confidence,
            rationale=_build_rationale(top.event, cp, top.dt_seconds, top.score, unit),
        )
        attributions.append(Attribution(change_point=cp, suspects=suspects, card=card))

    return attributions
