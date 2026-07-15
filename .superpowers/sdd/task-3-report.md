# Task 3 Report: Preserve Truthful Provider Outcomes

## Scope

- Added per-source and per-ticker producer outcomes for `financial_metrics` and
  `event_inputs`, including explicit timeout/worker-failure outcomes for every
  requested ticker.
- Published the refresh manifest through `atomic_write_json()`.
- Preserved producer partial/failed evidence when local snapshots are consumed.
- Added `OptionalObservation(status, values, source_fingerprint)` and retained
  read-only Mapping compatibility for existing scorer callers.
- Kept all test writes under `tmp_path`; no strategy, data, or Task 4 changes.

## RED / GREEN

### Producer outcomes and timeout

- Handoff tests covered successful-empty, one-source partial, all-source failed,
  and timeout conservation.
- GREEN: the Task 3 producer/store/optional suites passed `40 passed`.
- The timeout regression uses a 50 ms deadline, asserts return below 250 ms,
  conserves both requested tickers, records `provider_timeout` for every family,
  and verifies non-waiting executor shutdown.

### Optional observation consumption

Fresh integration RED command:

```bash
uv run pytest \
  tests/screening/test_optional_feature_store.py::test_load_intraday_metrics_reads_snapshot_for_requested_tickers \
  tests/screening/test_scoring_feature_store.py::test_missing_optional_snapshot_stays_unavailable_in_scoring_summary -q
```

Result before the integration fix: `2 failed`.

- `OptionalObservation` had no `.get()`, breaking the production
  `strategy_scorer` compatibility path.
- Missing optional snapshots were converted from `unavailable` to `failed` in
  the canonical `scoring_features` block.

GREEN after the fix, including targeted strategy caller coverage:

```bash
uv run pytest \
  tests/screening/test_optional_feature_store.py::test_load_intraday_metrics_reads_snapshot_for_requested_tickers \
  tests/screening/test_scoring_feature_store.py::test_missing_optional_snapshot_stays_unavailable_in_scoring_summary \
  tests/screening/test_strategy_scorer.py \
  -k 'intraday or fund_flow or daily_flow' -q
```

Result: `10 passed, 65 deselected`.

## Canonical schema decision

The only writer emits this nested shape:

```text
ticker_outcomes[ticker] = {
  observation_status,
  families: {
    family: {
      observation_status,
      nonempty_count,
      source_parts_succeeded,
      source_parts_total,
      sources: {source: {observation_status, nonempty_count, failure_code?}},
      failure_code?
    }
  }
}
```

The consumer treats `families[family]` as authoritative. A migration-era flat
`ticker_outcomes[ticker][family]` shape is accepted only when `families` is
absent and is never written. Family aggregates are legacy fallback evidence;
they cannot override a more specific ticker-family outcome. Missing or invalid
canonical family/source entries fail closed. The adversarial regression places
canonical `partial` beside conflicting flat and aggregate `success` evidence;
the consumed result remains `partial`.

## Self-review

- Timeout workers only return immutable observation values. The main thread is
  the sole owner of `observations_by_ticker`, the returned payload, and manifest
  publication; late worker completion has no callback or reference that can
  mutate either after return.
- `shutdown(wait=False, cancel_futures=True)` makes the deadline path return
  promptly. A provider call already running cannot be forcibly stopped and may
  finish its own snapshot side effect later, but it cannot rewrite the manifest.
- Aggregate family status is emitted explicitly from all ticker-family statuses.
- `OptionalObservation` hashes the exact bytes read (`sha256:`); missing files
  use `None`, and malformed-but-readable files retain their real content hash.
- Only `SUCCESS` optional observations are recorded observed/usable. Missing is
  `UNAVAILABLE`; malformed is `FAILED`; requested-status aggregation preserves
  all-unavailable as unavailable and fails closed when any ticker failed.
- Removed unused manifest projections and the unneeded `source_outcomes`
  compatibility alias. No aggregate can promote a specific partial outcome.

## Verification

Task 3 suites:

```bash
uv run pytest tests/screening/test_scoring_feature_refresh.py \
  tests/screening/test_scoring_feature_store.py \
  tests/screening/test_optional_feature_store.py -q
```

Result: `40 passed`.

Task 2 regression suites:

```bash
uv run pytest tests/screening/test_scoring_feature_quality.py \
  tests/screening/test_scoring_feature_store.py \
  tests/screening/test_auto_pipeline_publication.py \
  tests/test_main_auto_feature_quality.py -q
```

Result: `172 passed`.

Additional verification:

- `python -m compileall` for all six Task 3 files: PASS.
- `git diff --check`: PASS.
- targeted Ruff on all six Task 3 files: PASS.

## Concerns

- Python cannot cancel a provider function once its thread is already running;
  the non-waiting timeout contract therefore isolates immutable manifest state
  rather than promising provider-call termination.
