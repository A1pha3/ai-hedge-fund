# Final branch fixes report

Status: DONE_WITH_CONCERNS

Base: `d545ea67`

## Implemented

- A — Entry settlement is one repository-owned `BEGIN IMMEDIATE` operation. It re-reads cash, trusted marks/NAV, `OPEN` + `EXIT_PENDING` exposure, serialized plan priority/reservations and ticker aggregation, then computes execution costs and a 100-share-lot quantity. It atomically fills or records an exact skip reason. The service supplies only observed open evidence and versioned costs.
- B — Entry plans are valid only on `planned_entry_date`. Late plans become `SKIPPED/entry_expired`; the exact-date unknown and unexecutable observations become `entry_queue_unknown` and `entry_unexecutable`. All paths retain one idempotent audit event and release reservations.
- C — Ledger schema is v2. The v1 migration adds explicit `legacy_unverified` provenance and maps ticker marks only to one eligible trade epoch. Legacy marks are archived; ambiguous mappings raise inside the migration transaction, leaving v1 intact. Already-v2 metadata is validated idempotently.
- D — Trades and `PLAN_CREATED` events retain immutable plan provenance: verification status, run id, manifest/input/ticker-cache fingerprints, reference close, next-session-open order contract, board rule, exact validity date, cost version and regime authorization. Verified plans fail closed on incomplete or mismatched provenance; v1 rows never masquerade as verified.
- E — `--as-of` is threaded into cohort construction and stable input snapshots. Only dated journal rows and referenced ticker price rows at or before cutoff are snapshotted and fingerprinted. Post-cutoff rows do not alter bundle bytes; consumed pre-cutoff mutation aborts publication. Cutoff exclusion counts are reported.
- F — Atomic publication now holds a nofollow directory descriptor and performs exclusive temp creation, file fsync, descriptor-relative replace, parent fsync, owned-temp cleanup and exact existing-mode preservation. Symlink/non-regular targets and symlink parents are rejected. Arbitrary directory-fsync errors propagate; only explicit unsupported errno values are tolerated.
- G — Plan insertion uses natural-key `ON CONFLICT ... DO NOTHING` followed by full contract equality validation. Weight, priority or provenance differences raise. BROKER_IMPORT mapping and the complete illegal lifecycle transition matrix are asserted.

## TDD RED evidence

- `uv run pytest tests/offensive/test_ledger_repository.py -q` — collection failed because `PlanProvenance` did not exist.
- `uv run pytest tests/offensive/test_daily_action_service.py -q` — 4 failed: unknown entries remained planned and late/next-day plans filled.
- `uv run pytest tests/research/test_exit_shadow_research.py::test_as_of_excludes_future_journal_and_price_evidence -q` — failed until cutoff semantics and fixture evidence dates were aligned.
- `uv run pytest tests/utils/test_atomic_files.py -q` — 6 failures exposed non-descriptor monkeypatch assumptions, swallowed directory fsync, and cleanup masking; implementation/tests were updated to the durable contract.
- Actual research smoke initially failed with an empty cohort because this isolated worktree contains only one price-cache CSV. This is recorded below and was not papered over.

## GREEN / verification evidence

- `uv run pytest tests/offensive/test_ledger_repository.py tests/offensive/test_daily_action_service.py -q` — 62 passed.
- `uv run pytest tests/research/test_exit_shadow_research.py tests/scripts/test_run_exit_shadow_research.py -q` — 143 passed (before adding the final CLI invariance regression).
- `uv run pytest tests/utils/test_atomic_files.py tests/offensive/test_trade_lifecycle.py -q` — 44 passed.
- `uv run pytest tests/offensive/ tests/research/test_exit_shadow_research.py tests/scripts/test_run_exit_shadow_research.py tests/utils/test_atomic_files.py -q` — 688 passed.
- `uv run pytest tests/screening/test_auto_pipeline_publication.py tests/screening/test_data_quality_manifest.py tests/test_main_auto_cache_refresh.py tests/offensive/test_daily_action_cache_refresh.py tests/offensive/test_daily_action_manifest_gate.py tests/scripts/test_generate_reports_manifest_script.py -q` — 262 passed.
- `uv run pytest tests/scripts/test_run_exit_shadow_research.py -q` — 51 passed after adding cutoff-filtered snapshot and byte-invariance coverage.
- `uv run pytest tests/offensive/test_ledger_repository.py tests/offensive/test_daily_action_manifest_gate.py tests/offensive/test_daily_action_service.py -q` — 87 passed after adding explicit authorization provenance.
- `uv run python -m compileall -q src scripts/run_exit_shadow_research.py` — exit 0.
- `git diff --check` — exit 0.
- Final aggregate: `uv run pytest tests/offensive/ tests/research/test_exit_shadow_research.py tests/scripts/test_run_exit_shadow_research.py tests/utils/test_atomic_files.py tests/screening/test_auto_pipeline_publication.py tests/screening/test_data_quality_manifest.py tests/test_main_auto_cache_refresh.py tests/scripts/test_generate_reports_manifest_script.py -q` — 906 passed in 9.83s.
- SQLite smoke: `PRAGMA integrity_check` = `ok`; `PRAGMA foreign_key_check` = `[]`; schema version = `2`.
- Isolated settlement/expiry/provenance smoke — 5 passed.
- `git status --short data/paper_trading data/paper_trading_backtest data/price_cache` — no changes; legacy inputs remain untouched.

## Concerns

- The requested actual full-data 2026-07-13 research metric smoke cannot be reproduced inside this isolated worktree: `data/price_cache` contains only `300308.csv`, so the real 133-pair journal has zero locally reconstructable price paths. Fixture-backed strict-cutoff/report tests pass, including exact bundle-byte invariance, and the code does not use network access.
- Concurrency is exercised with independent SQLite connections across threads, which validates SQLite serialization and deterministic priority/caps. A separate OS-process smoke was not added; SQLite `BEGIN IMMEDIATE` supplies the same cross-process lock boundary.
