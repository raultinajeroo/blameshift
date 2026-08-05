# Using blameshift as a GitHub Action

`action.yml` wraps the CLI so a CI job can detect a latency regression,
comment the evidence on the PR, and attach the full reports as artifacts —
without failing the build unless you ask it to.

## Minimal workflow

```yaml
name: latency triage
on:
  pull_request:

permissions:
  contents: read
  pull-requests: write   # only needed for the PR comment

jobs:
  blameshift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # produce series.csv + changes.json however your pipeline does it:
      # a benchmark-history export and a deploy/commit log
      - name: Export benchmark history
        run: ./ci/export-benchmarks.sh series.csv changes.json

      - uses: raultinajeroo/blameshift@main
        with:
          series: series.csv
          changes: changes.json
          # fail-on-regression: "true"  # opt in to failing the build
```

A working example that runs on this repository's own fixture-derived demo
data lives in `.github/workflows/blameshift-demo.yml`.

## Inputs

| input | default | meaning |
|---|---|---|
| `series` | (required) | path to the series CSV (`timestamp,value`) |
| `changes` | (required) | path to the changes JSON |
| `window` | `25` | samples on each side of a scanned split |
| `z-threshold` | `6.0` | robust z-score needed to open a candidate |
| `min-run` | `10` | post-shift samples that must stay on the shifted side |
| `lookback-hours` | `48` | how far before a regression to look for causes |
| `json-out` | `blameshift-report.json` | JSON report path (artifact) |
| `html-out` | `blameshift-report.html` | HTML report path (artifact) |
| `comment` | `true` | post the summary as a PR comment |
| `fail-on-regression` | `false` | fail the step when a regression is detected |
| `python-version` | `3.12` | Python used to run blameshift |

## Outputs

| output | meaning |
|---|---|
| `change-points` | number of change points detected |
| `regressions` | number of regression change points detected |

## What the PR comment contains

Every detected change point with direction, effect (ms and %), confidence,
top suspect with blame score, other candidates, and a one-paragraph
evidence-card rationale per regression. The footer names the two input
files the numbers were computed from; the JSON and HTML reports are
uploaded as a `blameshift-reports` artifact.

The action is advisory by default: `fail-on-regression` is `false`, so a
detected regression comments and uploads artifacts but does not fail the
build. Set it to `"true"` once you trust the signal on your own series —
check `blameshift eval --cases eval/cases` for labeled-corpus metrics
first.
