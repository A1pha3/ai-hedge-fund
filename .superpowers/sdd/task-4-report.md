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

Final verification:

- `uv run pytest tests/offensive/test_pit_evidence.py tests/offensive/test_cache_readiness.py tests/offensive/test_daily_action_cache_refresh.py tests/test_main_auto_cache_refresh.py -q` — **121 passed**.
- `uv run pytest tests/offensive/ tests/test_main_auto_cache_refresh.py -q` — **747 passed**.
