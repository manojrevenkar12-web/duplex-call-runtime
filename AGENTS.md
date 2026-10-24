# Working on duplex-call-runtime

## Fast feedback

- `pytest -q -m "not models"`: seconds, no models needed.
- `dcr fetch` then `pytest -q`: adds the real speech models and two whole simulated calls (real time).
- `ruff check src tests && ruff format --check src tests && mypy src`
- `cd web && npm test && npm run typecheck && npm run lint`
- `dcr eval --configs full`: the dev calls, about a minute each on two cores. `dcr eval` runs every
  configuration (ablations).

## Invariants

- The runtime decides from what a phone line carries. Nothing under `agent/`, `turn/`, `speech/`,
  `audio/`, `llm/router.py`, `serving/` or `server.py` reads a scenario's `expect` or imports `dcr.sim`.
  The simulator scores calls from the caller's side of the line (`sim/metrics.py`).
- Settings live in `config/` (settings.yaml, assets.yaml), not in code. Models are pinned by
  URL and SHA-256 in `config/assets.yaml`.
- A booking or a transfer never runs on a speculative reply; only read-only tools do.
- Health text, card or account numbers never appear in test calls; names and numbers are invented.
- Held-out calls: never change the runtime to pass `calls/heldout/<set>/`. Its first run
  (`reports/heldout/<set>/FIRST_RUN.md` and `first_run.json`) is never rewritten. If you study a
  set's failures, write `regression` to `calls/heldout/<set>/STATUS` and have someone who has not
  seen the code write a new set from `calls/WRITING_CALLS.md` only.
