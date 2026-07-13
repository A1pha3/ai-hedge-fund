# Phase 2 Task 5 Report — Auditable auto publication

## Outcome

Implemented a single `run_auto_pipeline()` owner for `--auto` canonical and
attempt publication. Healthy runs replace `auto_screening_YYYYMMDD.json`
atomically; degraded and fatal runs write unique
`auto_attempt_YYYYMMDD_RUNID.json` artifacts without replacing the last healthy
canonical. `--strict-quality` maps degraded to exit 3, fatal maps to 1, and a
busy pipeline lock maps to temporary-failure exit 75.

`run_auto_screening()` now holds the existing flock only through preparation,
compute, manifest adjudication, tracking, and publication, closes the fd on all
paths (including `progress.start()` and delegate failures), then performs
display/post-processing after lock release. Degraded output is display-only and
cannot update watchlists, PDFs, rebalance output, email, or webhooks.

## Publication and data-integrity design

- The compute function no longer writes the canonical report. Cache refresh and
  post-enrichment paths also no longer republish it; the canonical writer exists
  only in `src/screening/auto_pipeline.py`.
- Payloads are JSON-normalized once. Tracking receives that exact in-memory
  object and canonical serialization uses the same normalized value.
- The controller requires tracking to succeed before canonical replacement. To
  make the unavoidable cross-file crash window auditable, a crash-durable
  `pending` attempt containing the exact intended payload is atomically written
  before tracking. On success it is removed and the directory is fsynced; on
  tracking/publication failure it is atomically replaced by a fatal attempt.
- Input preparation refreshes the daily-action cache and freezes a run-bound,
  point-in-time snapshot. Price, fund-flow, and industry fingerprints exclude
  rows after the requested trade date. A second capture before adjudication
  fails closed if the cache changed during compute.
- The manifest covers the full actual scan domain (`price_cache` tickers), while
  run health depends on aggregate quality plus readiness of recommended tickers.
  Non-recommended blocked tickers remain recorded for Task 6 candidate-level
  enforcement and do not permanently freeze canonical publication.
- Candidate admission evidence is accepted only from exact-date
  `candidate_pool_{trade_date}.json`. Old and future snapshots cannot infer
  current listed/ST/industry state.
- Quality checks fail closed: freshness must be explicitly true; quality
  evidence must be non-empty and structurally valid; stale must be false,
  provider failures exactly integer zero, coverage exactly one, and cache
  refresh failures/partial results degrade the run.

## TDD evidence

RED cases were observed before implementation/fixes for the missing pipeline
module, missing `--strict-quality`, canonical/attempt semantics, JSON
normalization drift, lock fd leaks, busy exit behavior, NaN/date mismatch,
quality fail-open cases, missing manifest evidence, future-row fingerprinting,
cache mutation during compute, the full-scan-vs-recommended health regression,
and old/future candidate snapshot admission. Each was made GREEN with the
smallest corresponding production change.

Independent review found and drove fixes for tracking/canonical crash
auditability, non-run-bound snapshots, incomplete scan coverage, overly broad
health gating, and time-travel candidate admission. Final review approval:
zero remaining Critical, Important, or Minor findings.

## Verification (2026-07-13)

- `uv run pytest tests/screening/test_auto_pipeline_publication.py -v` —
  **29 passed**.
- `uv run pytest tests/test_main_auto_cache_refresh.py -v` — **13 passed**.
- Relevant publication/tracking/manifest/strict-as-of/lock/e2e suite —
  **144 passed**.
- `uv run pytest tests/offensive/ tests/test_main_auto_cache_refresh.py -q` —
  **409 passed in 3.77s**.
- Ruff passed for all task files. `src/main.py` passed with `F401` ignored
  because its five TYPE_CHECKING-only lazy-import warnings predate this task and
  are required for annotations used by deferred pipeline imports.
- `py_compile`, `git diff --check`, and canonical-writer search passed.

The worktree virtual environment initially lacked `scipy`; it was installed
only into `.venv` to run the existing baseline. No dependency/project manifest
was changed.

## Residual boundary

Tracking history and the canonical JSON cannot be committed as one filesystem
transaction. The pending-attempt protocol guarantees an audit/recovery anchor
for the controller-mandated tracking-before-canonical window, but automated
reconciliation of a process-kill remnant is outside Task 5.
