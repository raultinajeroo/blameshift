"""Tests for the labeled-case eval harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from blameshift.cli import main
from blameshift.eval import evaluate_case, evaluate_cases
from blameshift.series import InputError

CASES = Path(__file__).resolve().parent.parent / "eval" / "cases"


def test_committed_corpus_scores():
    report = evaluate_cases(CASES)
    assert report.n_cases == 6
    # The three planted seeds are all detected exactly and blamed correctly.
    assert report.precision_at_1 == 1.0
    # Benign cases produce no detections.
    assert report.false_positive_rate == 0.0
    # Planted boundaries are found exactly (delay 0) on this corpus.
    assert report.mean_detection_delay == 0.0
    # case-06 has no in-window events, so it must come back unattributed.
    unattributed = [c for c in report.cases if c.unattributed]
    assert [c.name for c in unattributed] == ["case-06-unattributable"]
    assert report.unattributed_rate == pytest.approx(0.25)
    assert report.n_missed == 0


def test_benign_case_flags_false_positive_only_when_detector_fires():
    result = evaluate_case(CASES / "case-04-benign-seed5")
    assert result.planted_index is None
    assert result.false_positive is False
    assert result.correct_top1 is None


def test_missing_cases_dir_errors_with_remedy():
    with pytest.raises(InputError, match="cases directory not found"):
        evaluate_cases("/nonexistent/cases")


def test_case_missing_truth_errors_with_remedy(tmp_path):
    (tmp_path / "series.csv").write_text("timestamp,value\n1,100\n2,101\n")
    (tmp_path / "changes.json").write_text('{"changes": []}')
    with pytest.raises(InputError, match="missing truth.json"):
        evaluate_case(tmp_path)


def test_eval_cli_runs_and_writes_json(tmp_path, capsys):
    out = tmp_path / "eval.json"
    rc = main(["eval", "--cases", str(CASES), "--json", str(out)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "precision@1" in text
    assert "false-positive rate" in text
    doc = json.loads(out.read_text())
    assert doc["metrics"]["precision_at_1"] == 1.0
    assert doc["corpus"].startswith("labeled synthetic")


def test_eval_cli_missing_dir_exit_2(capsys):
    rc = main(["eval", "--cases", "/nonexistent/cases"])
    assert rc == 2
    assert "cases directory not found" in capsys.readouterr().err
