# blameshift

**Find the change that broke your latency.** `blameshift` takes a latency time
series (CI benchmark history, a prod metrics export) plus a change log
(deploys, commits, config edits), detects where the latency distribution
shifted, and ranks which recorded change most likely caused each regression,
emitting an evidence card per regression with before/after statistics and a
plain-English rationale.

## Why this exists

In any system with frequent deploys, the question "which change made this
endpoint slower?" comes up constantly, and answering it by hand means staring
at a dashboard, eyeballing the inflection point, and then scrolling through a
deploy timeline hoping the timestamps line up. That manual hunt is slow,
error-prone, and usually happens while the regression is still burning.
`blameshift` automates the first pass: point it at the series and the change
log, and get a short, ranked, evidence-backed suspect list in seconds.

Clean-room implementation. Inspired by production performance work;
all code and data here are original and synthetic.

## Quickstart

```bash
pip install -e .

# Generate a synthetic demo: 400 samples with one planted +15% regression
# (answer key in truth.json).
blameshift simulate --out examples/demo --points 400 --seed 7

# Detect the shift and attribute blame.
blameshift run --series examples/demo/series.csv \
               --changes examples/demo/changes.json \
               --json report.json --html report.html
```

Actual terminal output (from the committed `examples/demo` data):

```
blameshift: 400 samples, 2026-01-05 00:00 UTC -> 2026-01-06 09:15 UTC
metric: latency (ms)

Detected 1 change point(s):
  #  time                  direction       effect   effect%   conf  top suspect
-------------------------------------------------------------------------------
  1  2026-01-05 20:00 UTC  regression      +31.2ms    +15.9%   0.82  deploy-482 (score 0.75)

[change point 1] 2026-01-05 20:00 UTC — regression
  median 196.3ms -> 227.5ms (+15.9%), z=27.9, persistence 25/25
  evidence card:
    suspect : deploy-482 — switch checkout to new inventory client (deploy)
    author  : alex.kim
    score   : 0.75 (temporal 0.45 + effect 0.10 + persistence 0.20)
    why     : deploy deploy-482 ("switch checkout to new inventory client", by alex.kim) landed 37 minutes before a +15.9% median shift (196ms -> 228ms) that persisted across all 25 subsequent samples. Blame score 0.75: temporal proximity dominates because the change landed inside the lookback window closest to the shift.
  other candidates:
    deploy-479 (score 0.30, 30.0 hours before)

wrote examples/demo/report.json
wrote examples/demo/report.html
```

The planted shift was at sample 240 (2026-01-05 20:00 UTC), caused by
`deploy-482`, detected exactly, blamed correctly, and the in-window decoy
`deploy-479` (30 hours earlier) ranked well below. The HTML report is a
single self-contained file (inline CSS and SVG, no JavaScript) with the
series sparkline, the change point marked, and the evidence cards.

## Use in CI (GitHub Action)

From clone to a PR comment in about ten minutes:

1. Fork or clone this repo and open a test PR — the bundled workflow
   `.github/workflows/blameshift-demo.yml` runs the action on the
   fixture-derived demo data in `examples/demo/` and posts the result as a
   PR comment. It never fails the build (`fail-on-regression` defaults to
   off).
2. To point it at your own data, export a benchmark history
   (`timestamp,value` CSV) and a change log (deploys/commits JSON) in your
   pipeline, then:

```yaml
      - uses: raultinajeroo/blameshift@main
        with:
          series: series.csv
          changes: changes.json
```

The action posts one comment per PR: detected change points with effect
size and confidence, the top suspect with its evidence-card rationale,
and other candidates. JSON and HTML reports are uploaded as workflow
artifacts. Inputs, outputs, and the full example are in
[docs/ACTION.md](docs/ACTION.md).

## Evaluating the detector

`blameshift eval` scores the pipeline against the labeled synthetic corpus
in `eval/cases` (planted regressions, benign series, and an unattributable
case; rebuildable via `eval/build_cases.py`):

```bash
blameshift eval --cases eval/cases
```

It reports precision@1, false-positive rate, mean detection delay, and
unattributed rate. All four numbers describe this small synthetic corpus
only (six cases; see `eval/README.md`) — they are a smoke check on the
pipeline, not a benchmark of real-world accuracy.

## Input formats

**Series CSV**: header `timestamp,value`, one latency sample (ms) per row.
`timestamp` is epoch seconds or ISO-8601.

```csv
timestamp,value
2026-01-05T00:00:00Z,197.5126
2026-01-05T00:05:00Z,196.2317
```

**Changes JSON**: a list (or an object with a `changes` key) of events:

```json
{"changes": [{"id": "deploy-482", "timestamp": "2026-01-05T19:23:00Z",
              "kind": "deploy", "title": "switch checkout to new inventory client",
              "author": "alex.kim"}]}
```

## How it works

Detection is a robust two-window scan with a CUSUM confirmation. A split
point slides through the series with `window` (default 25) samples on each
side; at each split the shift is measured as the difference of the two window
medians, scaled by a pooled MAD (median absolute deviation, with the usual
1.4826 consistency factor) so the z-score is insensitive to outliers. A split
becomes a candidate when `|z| >= z_threshold` (default 6.0) and the shift
persists (at least `min_run` of the following samples stay on the shifted
side), which is what rejects single-point spikes. Each candidate is then
confirmed by a one-sided CUSUM from the split onward: the cumulative
deviation from the pre-shift median must exceed `k * MAD`, so random-walk
noise cannot pass. Candidates from the same shift merge into one cluster,
and the change point is placed at the cluster center (the candidate band of
a real level shift is symmetric around the true boundary).

Blame ranks every recorded change in the lookback window (default 48h) before
a regression by `w1 * exp(-dt/tau) + w2 * effect + w3 * persistence`.
Temporal proximity dominates, scaled by how large and how durable the
regression is. If nothing was recorded in the window, the output says
"unattributed" rather than pointing at a distant event.

Honest limits: this detects abrupt **level shifts**, not gradual drift; it
needs at least `2 * window` samples; and strongly seasonal series should be
deseasonalized first (a seasonal swing is not a deploy, but a naive scan
can't always tell them apart near the threshold).

## JSON output schema

```json
{
  "tool": "blameshift",
  "version": "0.1.0",
  "metric": "latency (ms)",
  "samples": 400,
  "range_utc": ["2026-01-05 00:00 UTC", "2026-01-06 09:15 UTC"],
  "change_points": [
    {
      "index": 240,
      "timestamp": 1767643200.0,
      "time_utc": "2026-01-05 20:00 UTC",
      "direction": "regression",
      "effect_ms": 31.1595,
      "effect_pct": 15.8698,
      "confidence": 0.8231,
      "z": 27.925,
      "median_before_ms": 196.3448,
      "median_after_ms": 227.5043,
      "persistence": 1.0,
      "persist_count": 25,
      "window": 25,
      "attribution": {
        "change_id": "deploy-482",
        "kind": "deploy",
        "title": "switch checkout to new inventory client",
        "author": "alex.kim",
        "dt_seconds": 2220.0,
        "score": 0.7464,
        "score_breakdown": {"temporal": 0.4512, "effect": 0.0952, "persistence": 0.2},
        "rationale": "deploy deploy-482 (...) landed 37 minutes before ..."
      },
      "suspects": [
        {"change_id": "deploy-482", "score": 0.7464, "...": "..."},
        {"change_id": "deploy-479", "score": 0.2986, "...": "..."}
      ]
    }
  ]
}
```

`attribution` is `null` for improvements, and `{"unattributed": "..."}` when
no change was recorded in the lookback window.

## Configuration

| Flag | Default | Meaning |
|---|---|---|
| `--window` | 25 | samples on each side of a scanned split |
| `--z-threshold` | 6.0 | robust z-score needed to open a candidate |
| `--min-run` | 10 | post-shift samples that must stay on the shifted side |
| `--cusum-k` | 8.0 | CUSUM confirmation depth, in units of MAD |
| `--lookback-hours` | 48 | how far before a regression to look for causes |
| `--tau-hours` | 6 | decay constant of the temporal proximity term |
| `--pr-comment PATH` | off | also write a markdown PR-comment summary |
| `--fail-on-regression` | off | exit 1 when a regression is detected |

Exit codes: `0` on success (including "no change points found"), `1` when
`--fail-on-regression` is set and a regression is detected, `2` on invalid
input. Error messages name the file, the location of the problem, and what
to fix (a missing file suggests generating demo data; a too-short series
tells you the minimum length for the chosen `--window`).

## Development

```bash
pip install -e . pytest
python -m pytest -q
```

## Roadmap

- Seasonality-aware baselines (deseasonalize before scanning, or model the
  seasonal component explicitly), so strong daily/weekly cycles never
  approach the threshold.
- Multi-metric correlation: when p50, p95, and error rate shift together,
  say so; when only one moves, that is evidence too.
- Optional LLM narrative hook: feed the evidence cards (structured, local
  data only) to a user-supplied model endpoint for a richer write-up. The
  core tool stays offline and deterministic.

## License

MIT. See [LICENSE](LICENSE). Copyright (c) 2026 Raul Tinajero Olivas.
