# Roadmap

Directions under consideration. Nothing on this page is implemented or
claimed as working today; the README documents only what the code does now.

## Planned / under consideration

- **Seasonality-aware baselines.** Deseasonalize before scanning, or model
  the seasonal component explicitly, so strong daily/weekly cycles never
  approach the detection threshold.
- **Multi-metric correlation.** When p50, p95, and error rate shift
  together, say so; when only one moves, that is evidence too.
- **Optional LLM narrative hook.** Feed the evidence cards (structured,
  local data only) to a user-supplied model endpoint for a richer write-up.
  The core tool would stay offline and deterministic; this would be strictly
  opt-in.

## Explicitly out of scope

- Live metric ingestion or dashboard integrations (the tool reads files).
- Real-time/alerting operation.
