"""Command-line interface: ``blameshift simulate`` and ``blameshift run``."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from . import __version__
from .blame import attribute
from .detectors import detect_change_points
from .eval import eval_to_json, evaluate_cases, render_eval
from .report import (
    render_pr_comment,
    render_terminal,
    render_html,
    to_json_dict,
    write_html,
    write_json,
)
from .series import InputError, load_changes_json, load_series_csv
from .simulate import generate, write_demo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blameshift",
        description="Find the change that broke your latency: detect where a "
        "latency series shifted and rank which recorded change most likely "
        "caused each regression.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sim = sub.add_parser(
        "simulate",
        help="generate a synthetic demo series with one planted regression",
    )
    sim.add_argument("--out", required=True, help="output directory for demo files")
    sim.add_argument("--points", type=int, default=400, help="number of samples (default 400)")
    sim.add_argument("--seed", type=int, default=7, help="RNG seed (default 7)")

    run = sub.add_parser(
        "run",
        help="detect change points in a series and attribute blame",
    )
    run.add_argument("--series", required=True, help="path to series CSV (timestamp,value)")
    run.add_argument("--changes", required=True, help="path to changes JSON")
    run.add_argument("--metric", choices=["latency", "probability"], default="latency",
                     help="latency in ms (default) or YES order-book midpoint in [0, 1]")
    run.add_argument("--json", dest="json_out", help="also write a JSON report to this path")
    run.add_argument("--html", dest="html_out", help="also write a single-file HTML report to this path")
    run.add_argument("--window", type=int, default=25, help="scan window size n (default 25)")
    run.add_argument("--z-threshold", type=float, default=6.0, help="robust z threshold (default 6.0)")
    run.add_argument("--min-run", type=int, default=10, help="required persistence in samples (default 10)")
    run.add_argument("--cusum-k", type=float, default=8.0, help="CUSUM confirmation multiplier k (default 8.0)")
    run.add_argument("--lookback-hours", type=float, default=48.0, help="blame lookback window in hours (default 48)")
    run.add_argument("--tau-hours", type=float, default=6.0, help="temporal decay constant in hours (default 6)")
    run.add_argument(
        "--pr-comment",
        dest="pr_comment_out",
        metavar="PATH",
        help="also write a markdown PR-comment summary to this path",
    )
    run.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="exit 1 if any regression change point is detected (default off)",
    )

    ev = sub.add_parser(
        "eval",
        help="score the pipeline against a directory of labeled cases",
    )
    ev.add_argument(
        "--cases",
        required=True,
        help="directory of labeled cases (each: series.csv, changes.json, truth.json)",
    )
    ev.add_argument("--json", dest="json_out", help="also write metrics JSON to this path")
    ev.add_argument("--window", type=int, default=25, help="scan window size n (default 25)")
    ev.add_argument("--z-threshold", type=float, default=6.0, help="robust z threshold (default 6.0)")
    ev.add_argument("--min-run", type=int, default=10, help="required persistence in samples (default 10)")
    ev.add_argument("--cusum-k", type=float, default=8.0, help="CUSUM confirmation multiplier k (default 8.0)")
    ev.add_argument("--lookback-hours", type=float, default=48.0, help="blame lookback window in hours (default 48)")
    ev.add_argument("--tau-hours", type=float, default=6.0, help="temporal decay constant in hours (default 6)")

    return parser


def _cmd_simulate(args: argparse.Namespace) -> int:
    try:
        result = generate(points=args.points, seed=args.seed)
    except ValueError as exc:
        print(f"blameshift: error: {exc}", file=sys.stderr)
        return 2
    series_path, changes_path, truth_path = write_demo(result, args.out)
    print(f"wrote {series_path}")
    print(f"wrote {changes_path}")
    print(f"wrote {truth_path}")
    print(
        f"planted: +{result.shift_pct:.0f}% shift at sample "
        f"{result.planted_index}, caused by {result.planted_event_id}"
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    probability = args.metric == "probability"
    unit = "" if probability else "ms"
    display = {"metric_label": "YES probability (order-book mid)" if probability
               else "latency (ms)", "unit": unit}
    try:
        if probability and args.fail_on_regression:
            raise InputError("--fail-on-regression applies only to --metric latency")
        points = load_series_csv(args.series)
        if probability and any(not 0 <= point.value <= 1 for point in points):
            raise InputError(f"{args.series}: probability values must be in [0, 1]")
        events = load_changes_json(args.changes)
        if len(points) < 2 * args.window:
            raise InputError(
                f"{args.series}: {len(points)} samples is too few for "
                f"window={args.window} (need at least {2 * args.window}); "
                "provide a longer series or lower --window"
            )
        change_points = detect_change_points(
            points,
            window=args.window,
            z_threshold=args.z_threshold,
            min_run=args.min_run,
            k=args.cusum_k,
        )
        if probability:
            change_points = [replace(cp, direction="increase" if cp.effect_ms > 0
                                     else "decrease") for cp in change_points]
    except (InputError, ValueError) as exc:
        print(f"blameshift: error: {exc}", file=sys.stderr)
        return 2

    if not events:
        print(
            f"blameshift: note: {args.changes} records no changes; any "
            "shift eligible for attribution will be unattributed. "
            "Record events in the changes file to rank temporal associations.",
            file=sys.stderr,
        )

    attributions = attribute(
        change_points,
        events,
        lookback_hours=args.lookback_hours,
        tau_hours=args.tau_hours,
        unit=unit,
    )

    print(render_terminal(points, attributions, **display))

    if args.json_out:
        doc = to_json_dict(points, attributions, **display)
        write_json(doc, args.json_out)
        print(f"\nwrote {args.json_out}")
    if args.html_out:
        write_html(render_html(points, attributions, **display), args.html_out)
        print(f"wrote {args.html_out}")
    if args.pr_comment_out:
        comment = render_pr_comment(
            points,
            attributions,
            series_path=args.series,
            changes_path=args.changes,
            **display,
        )
        with open(args.pr_comment_out, "w", encoding="utf-8") as fh:
            fh.write(comment + "\n")
        print(f"wrote {args.pr_comment_out}")

    if args.fail_on_regression and any(
        cp.direction == "regression" for cp in change_points
    ):
        print(
            "blameshift: regression change point(s) detected and "
            "--fail-on-regression is set",
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    try:
        report = evaluate_cases(
            args.cases,
            window=args.window,
            z_threshold=args.z_threshold,
            min_run=args.min_run,
            cusum_k=args.cusum_k,
            lookback_hours=args.lookback_hours,
            tau_hours=args.tau_hours,
        )
    except (InputError, ValueError) as exc:
        print(f"blameshift: error: {exc}", file=sys.stderr)
        return 2

    print(render_eval(report))
    if args.json_out:
        write_json(eval_to_json(report), args.json_out)
        print(f"\nwrote {args.json_out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "simulate":
        return _cmd_simulate(args)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "eval":
        return _cmd_eval(args)
    parser.error("unknown command")  # pragma: no cover
    return 2


if __name__ == "__main__":
    sys.exit(main())
