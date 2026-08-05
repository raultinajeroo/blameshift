"""Labeled-case evaluation for the detector + attribution pipeline.

``blameshift eval --cases eval/cases`` runs every labeled case in a
directory (one subdirectory per case, each with ``series.csv``,
``changes.json``, and a ``truth.json`` answer key) and reports aggregate
metrics:

* **precision@1** — of the planted regressions that were detected and had
  a true culprit recorded, the fraction whose top suspect is that culprit;
* **false-positive rate** — of the benign cases (no planted shift), the
  fraction where any change point was detected;
* **mean detection delay** — mean absolute distance, in samples, between
  the detected change point and the planted boundary (detected cases only);
* **unattributed rate** — of the detected planted regressions with a true
  culprit, the fraction that came back unattributed.

All numbers are derived from the labeled synthetic corpus passed in; they
describe this pipeline on this corpus, nothing more.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .blame import attribute
from .detectors import detect_change_points
from .series import InputError, load_changes_json, load_series_csv


@dataclass(frozen=True)
class CaseResult:
    """Outcome of running the pipeline on one labeled case."""

    name: str
    planted_index: int | None
    planted_event_id: str | None
    detected_index: int | None      # nearest detected regression, if in tolerance
    detection_delay: int | None     # detected_index - planted_index, in samples
    top_suspect_id: str | None
    false_positive: bool            # benign case with any detection
    missed: bool                    # planted case with no in-tolerance detection
    correct_top1: bool | None       # None when not applicable / not detected
    unattributed: bool              # detected planted regression without blame


@dataclass(frozen=True)
class EvalReport:
    """Aggregate metrics over a corpus of labeled cases."""

    cases: list[CaseResult] = field(default_factory=list)
    window: int = 25

    @property
    def n_cases(self) -> int:
        return len(self.cases)

    @property
    def precision_at_1(self) -> float | None:
        scored = [c for c in self.cases if c.correct_top1 is not None]
        if not scored:
            return None
        return sum(1 for c in scored if c.correct_top1) / len(scored)

    @property
    def false_positive_rate(self) -> float | None:
        benign = [c for c in self.cases if c.planted_index is None]
        if not benign:
            return None
        return sum(1 for c in benign if c.false_positive) / len(benign)

    @property
    def mean_detection_delay(self) -> float | None:
        delays = [abs(c.detection_delay) for c in self.cases if c.detection_delay is not None]
        if not delays:
            return None
        return sum(delays) / len(delays)

    @property
    def unattributed_rate(self) -> float | None:
        detected = [
            c
            for c in self.cases
            if c.planted_event_id is not None and not c.missed
        ]
        if not detected:
            return None
        return sum(1 for c in detected if c.unattributed) / len(detected)

    @property
    def n_missed(self) -> int:
        return sum(1 for c in self.cases if c.missed)


def load_case(case_dir: str | Path) -> tuple[list, list, dict]:
    """Load one case directory: series.csv, changes.json, truth.json."""
    case_dir = Path(case_dir)
    if not case_dir.is_dir():
        raise InputError(f"case directory not found: {case_dir}")
    truth_path = case_dir / "truth.json"
    if not truth_path.is_file():
        raise InputError(
            f"{case_dir}: missing truth.json answer key; each eval case "
            "needs series.csv, changes.json, and truth.json"
        )
    points = load_series_csv(case_dir / "series.csv")
    events = load_changes_json(case_dir / "changes.json")
    try:
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"{truth_path}: invalid JSON: {exc}") from None
    for key in ("planted_index", "planted_event_id"):
        if key not in truth:
            raise InputError(f"{truth_path}: missing required key {key!r}")
    return points, events, truth


def evaluate_case(
    case_dir: str | Path,
    *,
    window: int = 25,
    z_threshold: float = 6.0,
    min_run: int = 10,
    cusum_k: float = 8.0,
    lookback_hours: float = 48.0,
    tau_hours: float = 6.0,
    tolerance_samples: int | None = None,
) -> CaseResult:
    """Run detection + attribution on one case and score it against truth."""
    points, events, truth = load_case(case_dir)
    planted_index = truth["planted_index"]
    planted_event_id = truth["planted_event_id"]
    tolerance = tolerance_samples if tolerance_samples is not None else window

    change_points = detect_change_points(
        points, window=window, z_threshold=z_threshold, min_run=min_run, k=cusum_k
    )

    if planted_index is None:
        return CaseResult(
            name=Path(case_dir).name,
            planted_index=None,
            planted_event_id=None,
            detected_index=None,
            detection_delay=None,
            top_suspect_id=None,
            false_positive=bool(change_points),
            missed=False,
            correct_top1=None,
            unattributed=False,
        )

    regressions = [cp for cp in change_points if cp.direction == "regression"]
    nearest = min(
        regressions, key=lambda cp: abs(cp.index - planted_index), default=None
    )
    if nearest is None or abs(nearest.index - planted_index) > tolerance:
        return CaseResult(
            name=Path(case_dir).name,
            planted_index=planted_index,
            planted_event_id=planted_event_id,
            detected_index=None,
            detection_delay=None,
            top_suspect_id=None,
            false_positive=False,
            missed=True,
            correct_top1=None,
            unattributed=False,
        )

    attributions = attribute(
        [nearest], events, lookback_hours=lookback_hours, tau_hours=tau_hours
    )
    attr = attributions[0]
    top = attr.top_suspect
    unattributed = attr.card is None
    correct_top1 = (
        None
        if planted_event_id is None or top is None
        else top.event.id == planted_event_id
    )
    return CaseResult(
        name=Path(case_dir).name,
        planted_index=planted_index,
        planted_event_id=planted_event_id,
        detected_index=nearest.index,
        detection_delay=nearest.index - planted_index,
        top_suspect_id=top.event.id if top is not None else None,
        false_positive=False,
        missed=False,
        correct_top1=correct_top1,
        unattributed=unattributed,
    )


def evaluate_cases(cases_dir: str | Path, **kwargs) -> EvalReport:
    """Score every case subdirectory under ``cases_dir``."""
    cases_dir = Path(cases_dir)
    if not cases_dir.is_dir():
        raise InputError(
            f"cases directory not found: {cases_dir}; point --cases at a "
            "directory of labeled cases (see eval/README.md)"
        )
    case_dirs = sorted(p for p in cases_dir.iterdir() if p.is_dir())
    if not case_dirs:
        raise InputError(
            f"{cases_dir}: no case subdirectories found; each case needs "
            "series.csv, changes.json, and truth.json"
        )
    results = [evaluate_case(d, **kwargs) for d in case_dirs]
    return EvalReport(cases=results, window=kwargs.get("window", 25))


def _fmt_metric(value: float | None, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.3f}{suffix}"


def render_eval(report: EvalReport) -> str:
    """Render the eval report as aligned plain text (labeled as synthetic)."""
    lines: list[str] = []
    lines.append(
        f"blameshift eval: {report.n_cases} labeled synthetic case(s), "
        f"detection tolerance {report.window} sample(s)"
    )
    lines.append("all metrics below are derived from this labeled corpus only")
    lines.append("")
    header = (
        f"{'case':<28} {'planted':>8} {'detected':>9} {'delay':>6} "
        f"{'top suspect':<14} verdict"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for c in report.cases:
        if c.planted_index is None:
            verdict = "FALSE POSITIVE" if c.false_positive else "clean (no detection)"
            lines.append(f"{c.name:<28} {'-':>8} {'-':>9} {'-':>6} {'-':<14} {verdict}")
            continue
        if c.missed:
            lines.append(
                f"{c.name:<28} {c.planted_index:>8} {'-':>9} {'-':>6} "
                f"{'-':<14} MISSED"
            )
            continue
        if c.unattributed:
            verdict = "unattributed"
        elif c.correct_top1:
            verdict = "correct"
        else:
            verdict = f"wrong (expected {c.planted_event_id})"
        lines.append(
            f"{c.name:<28} {c.planted_index:>8} {c.detected_index:>9} "
            f"{c.detection_delay:>+6} {(c.top_suspect_id or '-'):<14} {verdict}"
        )
    lines.append("")
    lines.append(f"precision@1:          {_fmt_metric(report.precision_at_1)}")
    lines.append(f"false-positive rate:  {_fmt_metric(report.false_positive_rate)}")
    lines.append(
        f"mean detection delay: {_fmt_metric(report.mean_detection_delay, ' samples')}"
    )
    lines.append(f"unattributed rate:    {_fmt_metric(report.unattributed_rate)}")
    if report.n_missed:
        lines.append(f"missed detections:    {report.n_missed} case(s)")
    return "\n".join(lines)


def eval_to_json(report: EvalReport) -> dict:
    """JSON-serializable form of the eval report."""
    return {
        "tool": "blameshift",
        "command": "eval",
        "corpus": "labeled synthetic cases (see truth.json per case)",
        "detection_tolerance_samples": report.window,
        "n_cases": report.n_cases,
        "metrics": {
            "precision_at_1": report.precision_at_1,
            "false_positive_rate": report.false_positive_rate,
            "mean_detection_delay_samples": report.mean_detection_delay,
            "unattributed_rate": report.unattributed_rate,
            "missed_cases": report.n_missed,
        },
        "cases": [
            {
                "name": c.name,
                "planted_index": c.planted_index,
                "planted_event_id": c.planted_event_id,
                "detected_index": c.detected_index,
                "detection_delay_samples": c.detection_delay,
                "top_suspect_id": c.top_suspect_id,
                "false_positive": c.false_positive,
                "missed": c.missed,
                "correct_top1": c.correct_top1,
                "unattributed": c.unattributed,
            }
            for c in report.cases
        ],
    }
