"""Probability inputs must retain their units and support both shift directions."""

import json

import pytest

from blameshift.cli import main


@pytest.mark.parametrize("before,after,direction", [(0.3, 0.7, "increase"),
                                                   (0.7, 0.3, "decrease")])
def test_probability_mode_all_outputs(tmp_path, capsys, before, after, direction):
    series, events = tmp_path / "series.csv", tmp_path / "events.json"
    start = 1767225600
    series.write_text("timestamp,value\n" + "".join(
        f"{start + i * 300},{before if i < 100 else after}\n" for i in range(200)
    ))
    events.write_text(json.dumps([{
        "id": "example-event", "timestamp": start + 99 * 300,
        "kind": "release", "title": "Synthetic event", "author": "fixture",
    }]))
    report, html, comment = [tmp_path / name for name in ("out.json", "out.html", "out.md")]
    assert main(["run", "--metric", "probability", "--series", str(series),
                 "--changes", str(events), "--json", str(report),
                 "--html", str(html), "--pr-comment", str(comment)]) == 0
    terminal = capsys.readouterr().out
    doc = json.loads(report.read_text())
    assert doc["metric"] == "YES probability (order-book mid)"
    cp, = doc["change_points"]
    assert cp["direction"] == direction
    assert cp["effect"] == pytest.approx(after - before)
    assert cp["median_before"] == before
    assert "effect_ms" not in cp
    assert cp["attribution"]["change_id"] == "example-event"
    for text in (terminal, html.read_text(), comment.read_text()):
        assert direction in text
        assert "example-event" in text
        assert "0.3000" in text
        assert "0.7000" in text
        assert "latency" not in text
        assert "0.3ms" not in text
        assert "temporal association" in text


@pytest.mark.parametrize("value", [-0.1, 1.1, float("inf")])
def test_probability_rejects_out_of_range(tmp_path, capsys, value):
    series, events = tmp_path / "series.csv", tmp_path / "events.json"
    series.write_text("timestamp,value\n" + "".join(f"{1000+i},{value}\n" for i in range(80)))
    events.write_text("[]")
    assert main(["run", "--metric", "probability", "--series", str(series),
                 "--changes", str(events)]) == 2
    assert "[0, 1]" in capsys.readouterr().err


def test_probability_does_not_accept_regression_gate(capsys):
    assert main(["run", "--metric", "probability", "--fail-on-regression",
                 "--series", "unused.csv", "--changes", "unused.json"]) == 2
    assert "--fail-on-regression" in capsys.readouterr().err
