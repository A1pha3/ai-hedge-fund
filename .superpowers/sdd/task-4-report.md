# Task 4 Report — Immutable Daily Action refresh evidence

## Scope

Task 4 now produces one conserved `DailyActionRefreshResult` for the frozen
Daily Action universe. The result retains the single daily batch, tri-state
suspension evidence, exact per-ticker statuses, canonical PIT fingerprints,
and immutable display counters. `main` passes that same object to readiness
publication without re-globbing or reconstructing cache truth.

## Independent-review hardening

- Price and fund-flow cache baselines are captured once, immediately after the
  universe is frozen and before any write. Refresh writers expose detached
  normalized artifacts before their atomic write; successful artifacts replace
  the baseline in memory. Outcome construction never reopens cache files after
  writes. Failed writes and invalid artifacts carry no trusted fingerprint.
- `PITEvidenceError` is the typed fail-closed boundary for canonical price and
  fund-flow evidence. Included PIT rows require the full schema, a valid date,
  an exact six-digit ticker identity, and finite non-boolean numerics. Missing,
  null, non-finite, boolean, and invalid string values are rejected rather than
  omitted or normalized to a shared null representation.
- `DailyActionRefreshResult` tuple-copies its universe and freezes exact-key
  outcomes, nested fingerprint maps, derived stats, and recursively nested
  compatibility counters. `SuspensionEvidence` copies tickers to a frozenset
  and validates status/ticker/fingerprint consistency.
- Suspension payloads are authoritative only when they are DataFrames with a
  `ts_code` column. Schema-valid empty frames mean `AVAILABLE_EMPTY`; malformed
  shapes or any invalid non-null ticker mean `UNAVAILABLE`.
- Daily batches are detached and fully validated at the boundary. Malformed
  types, schemas, dates, identities, or numerics produce an exact-key frozen
  result with failed price evidence and no batch fingerprint; they do not
  escape through limit-up extraction, cache writing, or fingerprinting.
- Beijing Exchange exclusion, stale-flow quota `NOT_ATTEMPTED`, pre-existing
  current-flow handling, one-batch fetching, and suspension semantics remain
  covered by the existing regression suite. No strategy behavior or parameter
  was changed.

## Second independent-review hardening

- PIT numerics now use an explicit scalar allow-list: built-in integers,
  floats, `Decimal`, supported NumPy integer/floating scalars, and explicitly
  parsed strings. Arbitrary objects are rejected before `str()` can turn them
  into evidence that collides with a real numeric value.
- Cache capture now retains two detached views from one pre-write read: the
  complete baseline used only for merge/persistence, and the point-in-time
  projection used for fingerprints, current-state checks, and history row
  counts. Refreshing an earlier trade date therefore preserves later rows.
- Complete price and fund-flow artifacts are strictly validated before the
  artifact sink and before `atomic_write_csv`. Any malformed provider row or
  baseline leaves the existing file byte-for-byte unchanged and produces a
  failed outcome without a fingerprint.
- A nonempty suspension snapshot containing any null identity is unavailable;
  only a zero-row DataFrame with the authoritative schema proves an available
  empty set.
- Outcome fingerprints, reasons, warnings, history counts, and derived stats
  counts now have narrow type validation. Mutable input mappings/lists are
  detached, while invalid nested or boolean/non-integer count values are
  rejected at construction.

## Third independent-review hardening

- `DailyActionRefreshResult` now accepts only the exact frozen
  `SuspensionEvidence` and `DailyActionCacheRefreshStats` types. After outcomes
  are detached, price and fund-flow counts are re-derived from those frozen
  outcomes and must exactly equal the corresponding stats mappings. Industry
  index and limit-up metadata remain carried by the supplied immutable stats
  object unchanged.
- `FundFlowStore` now supports legacy CSVs whose `ticker` column is wholly
  absent by imputing the requested storage identity before concat and
  validation. This retains generic backfill identifiers such as `X`. Any
  explicit mismatched, mixed, or partially null identity still fails before
  persistence.

## TDD evidence

The independent-review fixes were implemented through explicit RED/GREEN
cycles:

- Strict PIT validation RED: 30 failures; GREEN: 33 passing tests before the
  final typed date/ticker additions.
- Model ownership/consistency RED: 7 failures; GREEN: 19 passing tests.
- Provider-boundary RED: 15 failures and 1 existing pass; GREEN: 16 targeted
  passes.
- Captured-artifact binding RED: 3 failures; GREEN: 3 targeted passes.
- Pre-atomic DataFrame-copy and typed adapter RED: 5 failures; GREEN: 11
  targeted passes.
- Arbitrary malformed scalar / invalid suspension collection RED: 2 failures;
  GREEN: 16 targeted passes.
- Numeric impostor RED: 1 failure; GREEN: 40 PIT evidence tests.
- Full-baseline preservation RED: 2 failures; GREEN: price and flow future-row
  preservation with PIT-only row counts.
- Pre-write artifact validation RED: 2 failures; GREEN: malformed price
  baseline and flow provider leave persisted bytes unchanged.
- Null suspension identities RED: 2 failures; GREEN: 10 schema-boundary cases.
- Outcome value validation RED: 10 failures, plus 3 aggregate fingerprint
  failures; GREEN: all nested-value, count, and aggregate constructor cases.
- Full-suite integration exposed 6 generic backfill identifier regressions;
  the storage validator was narrowed without weakening six-digit Daily Action
  evidence identity, and all 14 backfill tests then passed.
- Aggregate type/count contract RED: 6 failures; GREEN: exact frozen types,
  exact outcome-derived price/flow counts, and preserved auxiliary stats.
- Legacy flow identity RED: 1 missing-column failure while the mismatch guard
  already passed; GREEN: 6 store tests and 20 combined generic flow tests.

Final verification:

- `uv run pytest tests/offensive/test_pit_evidence.py tests/offensive/test_cache_readiness.py tests/offensive/test_daily_action_cache_refresh.py tests/test_main_auto_cache_refresh.py -q` — **148 passed**.
- `uv run pytest tests/offensive/test_fund_flow_store.py tests/offensive/test_backfill_fund_flow.py -q` — **20 passed**.
- `uv run pytest tests/offensive/ tests/test_main_auto_cache_refresh.py -q` — **776 passed**.
