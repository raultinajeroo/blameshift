"""Blame attribution: ranking, decoys, empty windows, improvements."""

from __future__ import annotations

import pytest

from blameshift import ChangeEvent, ChangePoint, attribute

T0 = 1_767_657_600.0


def make_cp(direction: str = "regression", timestamp: float = T0) -> ChangePoint:
    sign = 1.0 if direction == "regression" else -1.0
    return ChangePoint(
        index=200,
        timestamp=timestamp,
        direction=direction,
        effect_ms=sign * 30.0,
        effect_pct=sign * 14.2,
        confidence=0.9,
        z=sign * 12.0,
        median_before=212.0,
        median_after=212.0 + sign * 30.0,
        persist_count=25,
        window=25,
        cusum_extreme=900.0,
    )


def event(id_: str, seconds_before: float, kind: str = "deploy") -> ChangeEvent:
    return ChangeEvent(
        id=id_,
        timestamp=T0 - seconds_before,
        kind=kind,
        title=f"title for {id_}",
        author="someone",
    )


def test_culprit_ranked_above_decoys():
    culprit = event("deploy-482", 37 * 60)          # 37 minutes before
    near_decoy = event("deploy-479", 30 * 3600)     # 30 hours before
    far_decoy = event("deploy-471", 6 * 86400)      # outside the 48h window

    (attr,) = attribute([make_cp()], [far_decoy, near_decoy, culprit])

    assert attr.top_suspect is not None
    assert attr.top_suspect.event.id == "deploy-482"
    # Every decoy still inside the window scores strictly lower.
    suspect_ids = [s.event.id for s in attr.suspects]
    assert "deploy-479" in suspect_ids
    assert suspect_ids.index("deploy-482") < suspect_ids.index("deploy-479")
    assert attr.suspects[0].score > attr.suspects[1].score
    # The far decoy is outside the lookback window entirely.
    assert "deploy-471" not in suspect_ids


def test_score_breakdown_components_sum_to_total():
    (attr,) = attribute([make_cp()], [event("deploy-482", 37 * 60)])

    s = attr.suspects[0]
    assert s.score == pytest.approx(
        s.temporal_score + s.effect_score + s.persistence_score
    )
    # 37 minutes << tau (6h): temporal proximity should be near its max.
    assert s.temporal_score == pytest.approx(0.5, abs=0.05)


def test_no_events_in_window_is_honest():
    far = event("deploy-460", 10 * 86400)

    (attr,) = attribute([make_cp()], [far])

    assert attr.suspects == []
    assert attr.card is None
    assert attr.unattributed_reason is not None
    assert "no recorded changes" in attr.unattributed_reason


def test_events_after_shift_are_not_blamed():
    future = ChangeEvent(
        id="config-114",
        timestamp=T0 + 2 * 86400,
        kind="config",
        title="raise connection pool ceiling",
        author="alex.kim",
    )

    (attr,) = attribute([make_cp()], [future])

    assert attr.suspects == []
    assert attr.unattributed_reason is not None


def test_improvement_is_not_blamed():
    culprit = event("deploy-482", 37 * 60)

    (attr,) = attribute([make_cp(direction="improvement")], [culprit])

    assert attr.suspects == []
    assert attr.card is None
    assert attr.unattributed_reason is None


def test_evidence_card_contents():
    culprit = ChangeEvent(
        id="deploy-482",
        timestamp=T0 - 37 * 60,
        kind="deploy",
        title="switch checkout to new inventory client",
        author="alex.kim",
    )

    (attr,) = attribute([make_cp()], [culprit])
    card = attr.card

    assert card is not None
    assert card.change_id == "deploy-482"
    assert card.author == "alex.kim"
    assert card.dt_seconds == pytest.approx(37 * 60)
    assert card.median_before == pytest.approx(212.0)
    assert card.median_after == pytest.approx(242.0)
    assert "+14.2%" in card.rationale
    assert "212ms -> 242ms" in card.rationale
    assert "37 minutes" in card.rationale
    assert "deploy-482" in card.rationale


def test_invalid_blame_parameters_rejected():
    with pytest.raises(ValueError):
        attribute([make_cp()], [], lookback_hours=0)
    with pytest.raises(ValueError):
        attribute([make_cp()], [], tau_hours=-1)
    with pytest.raises(ValueError):
        attribute([make_cp()], [], weights=(0.5, 0.5, 0.5))
