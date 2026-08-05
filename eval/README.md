# Eval corpus

Labeled synthetic cases used by `blameshift eval`. Every case is generated
by `blameshift.simulate` with a fixed seed; no real latency data is
involved. Metrics computed here describe this pipeline on this corpus only.

Rebuild the corpus deterministically:

```bash
python eval/build_cases.py   # requires blameshift installed (pip install -e .)
```

Run the evaluation:

```bash
blameshift eval --cases eval/cases
```

## Case layout

One directory per case, each with:

- `series.csv` — the latency series (`timestamp,value`)
- `changes.json` — the recorded change log given to the tool
- `truth.json` — the answer key (`planted_index`, `planted_event_id`),
  read only by `blameshift eval`, never by `blameshift run`

## Cases

| case | kind | expectation |
|---|---|---|
| case-01-planted-seed7 | planted +15% regression at sample 240 | detected, blamed on deploy-482 |
| case-02-planted-seed11 | same scenario, different seed | detected, blamed on deploy-482 |
| case-03-planted-seed23 | same scenario, different seed | detected, blamed on deploy-482 |
| case-04-benign-seed5 | stationary, no shift | no detection |
| case-05-benign-seed13 | stationary, no shift | no detection |
| case-06-unattributable | planted regression, in-window events stripped from the log | detected, reported unattributed |

Six hand-built cases is a smoke corpus, not a benchmark; the metrics are
labeled accordingly in the eval output. A larger and more adversarial
corpus (gradual drift, seasonality near the threshold, multiple shifts) is
on the roadmap.
