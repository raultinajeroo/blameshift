"""CLI end-to-end and input-validation behavior."""

from __future__ import annotations

import json

import pytest

from blameshift.cli import main


def test_simulate_then_run_end_to_end(tmp_path, capsys):
    demo = tmp_path / "demo"
    rc = main(["simulate", "--out", str(demo), "--points", "400", "--seed", "7"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "planted" in out
    for name in ("series.csv", "changes.json", "truth.json"):
        assert (demo / name).is_file()

    json_out = tmp_path / "report.json"
    html_out = tmp_path / "report.html"
    rc = main(
        [
            "run",
            "--series", str(demo / "series.csv"),
            "--changes", str(demo / "changes.json"),
            "--json", str(json_out),
            "--html", str(html_out),
        ]
    )
    assert rc == 0

    terminal = capsys.readouterr().out
    assert "Detected 1 change point(s)" in terminal
    assert "deploy-482" in terminal
    assert "regression" in terminal
    assert "evidence card" in terminal

    doc = json.loads(json_out.read_text())
    assert doc["tool"] == "blameshift"
    assert doc["samples"] == 400
    (cp,) = doc["change_points"]
    assert cp["direction"] == "regression"
    assert cp["attribution"]["change_id"] == "deploy-482"
    assert set(cp["attribution"]["score_breakdown"]) == {
        "temporal", "effect", "persistence",
    }
    assert cp["attribution"]["rationale"]

    html = html_out.read_text()
    assert "<svg" in html
    assert "deploy-482" in html
    assert "evidence cards" in html


def test_run_stable_series_reports_no_change_points(tmp_path, capsys):
    assert main(["simulate", "--out", str(tmp_path / "demo")]) == 0
    capsys.readouterr()

    # Rewrite the series as perfectly stable: detection must stay silent.
    import numpy as np

    rng = np.random.default_rng(21)
    lines = ["timestamp,value"]
    base = 1_767_657_600.0
    for i, v in enumerate(200.0 + rng.normal(0.0, 3.0, size=300)):
        lines.append(f"{base + i * 300.0},{v:.4f}")
    series = tmp_path / "stable.csv"
    series.write_text("\n".join(lines) + "\n")

    rc = main([
        "run",
        "--series", str(series),
        "--changes", str(tmp_path / "demo" / "changes.json"),
    ])
    assert rc == 0
    assert "No change points detected" in capsys.readouterr().out


def test_run_missing_files_exit_2(tmp_path, capsys):
    rc = main([
        "run",
        "--series", str(tmp_path / "nope.csv"),
        "--changes", str(tmp_path / "nope.json"),
    ])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_run_malformed_series_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text("timestamp,value\nnot-a-time,200\n")
    changes = tmp_path / "changes.json"
    changes.write_text('{"changes": []}')

    rc = main(["run", "--series", str(bad), "--changes", str(changes)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "line 2" in err
    assert "timestamp" in err


def test_run_malformed_changes_exit_2(tmp_path, capsys):
    series = tmp_path / "series.csv"
    series.write_text("timestamp,value\n" + "\n".join(
        f"{1_767_657_600.0 + i * 300},{200 + i % 3}" for i in range(80)
    ) + "\n")
    bad = tmp_path / "changes.json"
    bad.write_text('[{"id": "deploy-1", "kind": "deploy"}]')  # missing fields

    rc = main(["run", "--series", str(series), "--changes", str(bad)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "missing required field" in err
    assert "timestamp" in err


def test_loader_rejects_duplicate_timestamps(tmp_path):
    from blameshift import InputError, load_series_csv

    dup = tmp_path / "dup.csv"
    dup.write_text("timestamp,value\n1000,200\n1000,201\n")
    with pytest.raises(InputError, match="duplicate timestamp"):
        load_series_csv(dup)


def test_loader_rejects_bad_header(tmp_path):
    from blameshift import InputError, load_series_csv

    bad = tmp_path / "bad.csv"
    bad.write_text("time,ms\n1000,200\n")
    with pytest.raises(InputError, match="expected header"):
        load_series_csv(bad)


def test_loader_rejects_non_list_changes(tmp_path):
    from blameshift import InputError, load_changes_json

    bad = tmp_path / "bad.json"
    bad.write_text('{"events": []}')
    with pytest.raises(InputError, match="'changes' key"):
        load_changes_json(bad)


def test_loader_rejects_invalid_json(tmp_path):
    from blameshift import InputError, load_changes_json

    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(InputError, match="invalid JSON"):
        load_changes_json(bad)


def test_custom_window_and_threshold_flags(tmp_path, capsys):
    demo = tmp_path / "demo"
    assert main(["simulate", "--out", str(demo), "--points", "400", "--seed", "7"]) == 0
    capsys.readouterr()

    rc = main([
        "run",
        "--series", str(demo / "series.csv"),
        "--changes", str(demo / "changes.json"),
        "--window", "30",
        "--z-threshold", "5",
        "--lookback-hours", "72",
    ])
    assert rc == 0
    assert "Detected 1 change point(s)" in capsys.readouterr().out
