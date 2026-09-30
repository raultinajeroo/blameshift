# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `blameshift run --metric probability` consumes pmwatch midpoint CSVs,
  validates [0, 1], reports increases/decreases with probability units,
  and ranks events for both directions as temporal associations. The
  existing latency mode and JSON fields remain the default.
- Composite GitHub Action (`action.yml`) wrapping `blameshift run`, with an
  example PR workflow; advisory by default (`fail-on-regression` off).
- `blameshift run --pr-comment PATH`: markdown PR summary with change
  points, effect, confidence, top suspect, other candidates, and
  evidence-card rationale.
- `blameshift run --fail-on-regression`: exit 1 when a regression is
  detected.
- `blameshift eval --cases DIR`: labeled-case scoring (precision@1,
  false-positive rate, mean detection delay, unattributed rate) with a
  committed six-case synthetic corpus rebuildable via
  `eval/build_cases.py`.
- Benign (no-shift) series generator for false-positive evaluation.
- CI license check step (verifies `LICENSE` exists and is non-empty).
- Test covering the committed `examples/demo` fixtures running offline with
  no network or API keys.
- `ROADMAP.md`, `docs/IMPACT.md`, and GitHub issue templates (bug report,
  feature request).
- Short README for `examples/demo` explaining how to run the demo offline
  and that its numbers are fixture-derived.

### Changed

- CLI error messages now name the remedy: missing files suggest generating
  demo data, a too-short series states the minimum length for the chosen
  `--window`, and an empty change log warns that regressions will be
  unattributed.
- Moved not-yet-implemented roadmap items out of the README into
  `ROADMAP.md`.
- Relabeled an unlabeled performance claim in the README ("in seconds"
  became "in one command").
