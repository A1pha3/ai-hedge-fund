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

## External-review hardening addendum (2026-07-13)

The earlier residual boundary above is now closed by a restart-safe state
machine. Pending artifacts use schema version 1 and carry exact normalized
payload, `run_id`, trade date, manifest fingerprint, finalized input
fingerprint, payload checksum, state checksum, and durable phase:

`prepared → exact tracking replacement → tracked → canonical → unlink`

Every phase write uses the durable atomic JSON primitive. Recovery runs under
the existing outer auto flock before preheat, cache refresh, or compute. It
resumes and returns the interrupted run instead of starting a fresh run. A kill
after tracking but before the `tracked` write repeats the exact replacement
safely; a kill after canonical replacement but before phase persistence repeats
the same canonical atomically; a `canonical` remnant verifies/republishes the
exact payload before durable cleanup. Cleanup failures and recoveries are
returned as structured diagnostics and logged by the CLI wrapper.

Layer-A evidence is no longer inferred from `price_cache` or from a snapshot
that existed before compute. `_build_auto_screening_payload` carries the exact
candidate rows/ticker set returned by that compute call. After candidate_pool
writes the exact-date legacy snapshot, the pipeline verifies its ticker set,
then finalizes immutable `AutoInputs` for those tickers—including candidates
with no price-cache file—and binds trade date, run identity, candidate-set
fingerprint, snapshot fingerprint, and cache fingerprints into the manifest.
Snapshot/cache mutation before adjudication fails closed.

Payload-driven tracking now performs run-aware exact replacement for the run
date and stores `source_run_id`. Same-date orphan rows from an interrupted or
unpublished run are removed, score/model/price fields come from the recovered
payload, and other dates remain intact. Realized labels are preserved only when
the ticker/date/price/score/model identity is unchanged. History publication
now uses `atomic_write_json` under the existing tracking flock, providing file
fsync, atomic replace, directory fsync, permission preservation, and temp-file
cleanup.

Quality adjudication now requires `manifest.is_healthy is True` (plain bool),
explicit exact-int-zero `provider_failures`, cache status exactly `success`, and
explicit exact-int-zero values for `price_failed`, `price_missing`,
`price_insufficient_history`, `fund_flow_failed`, `fund_flow_empty`, and
`industry_index_failed`. Missing values, bools, strings, unsupported statuses,
and partial results all fail closed.

### Additional RED → GREEN evidence

- Import/behavior REDs proved the absence of post-compute input finalization,
  non-price-cache Layer-A coverage, stale-snapshot rejection, and run-id binding.
- The quality matrix initially produced 18 expected failures for missing/default
  provider failures, unsupported/missing statuses, and uncovered partial
  counters.
- Tracker REDs reproduced same-date orphan retention, stale scores/models,
  unconditional label retention, missing `source_run_id`, and permission loss.
- Six injected `BaseException` crash boundaries initially failed because no
  restart reconciliation or durable phases existed; all now resume the same
  payload without invoking new preparation.
- A cleanup-failure RED established that a durable `canonical` remnant must be
  surfaced rather than silently ignored.

### Additional verification

- Publication/recovery/tracker/cache/manifest/as-of/lock/e2e set:
  **269 passed**.
- Tracker-focused set: **82 passed**.
- Offensive plus auto-cache baseline: **410 passed in 4.05s**.
- Ruff passed for changed task files (`src/main.py` with only the same pre-existing
  TYPE_CHECKING `F401` exclusions), `py_compile` passed, and `git diff --check`
  was clean.

### Remaining operational concern

More than one checksum-valid pending run for the same trade date is treated as
fatal and left untouched for operator resolution; automatically choosing one
would risk publishing stale or unioned scores. This state should be impossible
under the outer flock, but fail-closed handling is intentional.

## Cross-date and immutable-input hardening addendum (2026-07-13)

The pre-compute snapshot is now a full immutable cache baseline across every
six-digit price/fund-flow cache name and every mapped industry-index series.
Healthy adjudication requires every exact Layer-A candidate to have existed in
that baseline with non-null price, fund-flow, and industry content, all
unchanged after compute. The manifest binds the full baseline fingerprint and
industry-content fingerprint. Candidate admission is compared as a canonical
projection—not merely a ticker set—covering name, industry, listing date,
security/ST state, and board-rule version, with its own run-bound fingerprint.

Pending recovery now uses the dedicated
`.auto_pending/YYYYMMDD/RUN_ID.json` namespace and discovers all dates before
any new compute. Exactly one valid state resumes its own bound date and
canonical filename; multiple states, corrupt JSON, disguised non-pending
files, unexpected namespace entries, renamed files, and checksum/identity
mismatches fail closed. Validation requires exact string dates and run IDs,
plain-int schema version, exact phase, state/payload/manifest/filename identity,
safe run IDs, and exact payload/manifest/input/state checksums. Unsafe injected
dependency run IDs are rejected and the diagnostic fallback generates a fresh
safe identifier, so they cannot influence filesystem paths.

### Third-pass RED → GREEN evidence

- Candidate files absent before compute, price/fund mutations during compute,
  industry-content mutation, and identical ticker sets with changed admission
  metadata all failed before the immutable-baseline/projection binding changes.
- Next-date invocation initially started a new run instead of recovering the
  older bound date. Cross-date discovery and bound canonical publication now
  recover only that older payload.
- Corrupt/disguised namespace files, bool/float schema versions, renamed state
  files, multiple cross-date states, unsafe dependency run IDs, non-string
  dates, and recomputed-checksum manifest identity substitution now all fail
  closed.

### Third-pass verification

- Publication and restart-hardening suite: **89 passed**.
- Publication/manifest/as-of/tracker/cache/feature/lock suite:
  **257 passed**.
- Offensive plus auto-cache baseline: **410 passed in 3.90s**.
- Ruff, `py_compile`, and `git diff --check` passed for all changed task files.

## Final closure addendum (2026-07-13)

`AutoRunResult` now exposes `effective_trade_date`. New runs bind it to the
validated requested date; recovery binds it to the validated pending-state
date. Recovery diagnostics include requested/effective dates and an explicit
`requested_date_executed` flag. The CLI independently validates that the result
date and payload date are exact and identical before any downstream work. A
July 10 invocation that finishes a July 9 recovery prints that July 10 was not
executed and uses July 9 for display, PDF/watchlist enrichment, attribution,
rebalance, and push handling.

Checksum validity is no longer sufficient to authorize canonical recovery.
Pending payloads must have exact `healthy` status and `auto_screening` mode;
their manifest must have exact `healthy` status and a plain-boolean `true`
health field, in addition to the existing date/run/filename/checksum bindings.
Tests recompute every affected checksum after semantic tampering and still
verify fail-closed behavior.

Candidate evidence no longer truncates or coerces ticker values. Both candidate
rows and their declared ticker list require exactly six ASCII digits before a
ticker can participate in cache-path construction. Full-width Unicode digits,
overlong values, symbols, path-like strings, and non-strings are rejected.

The `.auto_pending` root is inspected with `lstat` and must be a real,
non-symlink directory. This check runs before discovery and again during
publication; date directories receive the same non-symlink check, and root/date
device+inode identities are rechecked immediately before the durable write to
narrow replacement races. File and symlink roots fail closed before new
compute.

### Final closure RED → GREEN and verification

- The focused closure matrix initially produced **14 expected failures** for
  missing effective-date propagation, semantic checksum substitution,
  ticker coercion/truncation, and unsafe pending roots; it is now green.
- Publication plus main downstream suite: **116 passed**.
- Publication/manifest/as-of/tracker/cache/feature/lock suite:
  **270 passed**.
- Offensive plus auto-cache baseline: **411 passed in 3.50s**.
