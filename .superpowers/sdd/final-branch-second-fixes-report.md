# Final branch second fix wave

## Scope and root causes

This wave closes the seven remaining Important/Minor findings from the final
branch review without changing the production exit policy.

1. `LedgerRepository.fill_plan()` was a second, unrestricted transition path.
   It could write an entry independently of the serialized capacity/priority/
   expiry checks. It now delegates to the same `BEGIN IMMEDIATE` settlement
   transaction as the daily service. Explicit fills must be valid A-share lots,
   fit available cash, portfolio/ticker capacity and the fee-inclusive target
   notional. Repeated fills are idempotent and cannot append duplicate cash
   events.
2. The 12% cap was inferred from the requested weight. Cap authority now comes
   from immutable plan provenance: `legacy_unverified` and verified `normal`
   plans are capped at 10%; only verified BTST `btst_crisis` or
   `btst_risk_off` provenance permits 12%. Plan creation, service reservation
   and transactional fill all enforce the same rule.
3. The generic atomic writer previously protected only the final parent/target.
   `_open_parent()` now walks from `/` (or the held current directory) one
   component at a time with descriptor-relative `openat`, directory-only and
   `O_NOFOLLOW`, including safely created missing components. Any symlink in an
   intermediate ancestor is rejected.
4. Legacy journal EXIT `date` is the signal date, not an availability timestamp.
   New exit-shadow analysis therefore accepts only the current civil date and
   reports `historical_pit_eligible=false`,
   `journal_event_availability=unverifiable`, and source-snapshot `as_of`
   semantics. A historical invocation may only reuse an already committed
   bundle after verifying its marker, both artifact hashes, semantic identity,
   filenames and cross-hashes; an empty/forged marker cannot trigger analysis
   or bypass the policy. Price and journal evidence are still cut at `as_of`.
5. A due exact-date entry with an unavailable exact session or insufficient
   future holding calendar no longer remains planned indefinitely. It is
   atomically skipped as `entry_calendar_unavailable` and the run is blocked
   for calendar incompleteness.
6. v1 migration backfills every row with explicit `legacy_unverified`
   provenance and installs insert/update guards rejecting `NULL`, matching the
   behavioral non-null contract of a freshly created v2 ledger.
7. Cutoff audit counters are collected before ticker-consumption filtering and
   now count future journal rows and future rows/files/tickers across the full
   price-cache snapshot. They are published in JSON/Markdown. Appending future
   evidence truthfully changes bundle bytes/hashes, while the consumed-input
   fingerprint, analysis snapshot, fixed policy and paired statistics remain
   unchanged.

## Test evidence

- `uv run pytest tests/offensive/ tests/utils/test_atomic_files.py tests/research/ tests/scripts/test_run_exit_shadow_research.py -q`
  - `874 passed in 15.04s`
- `uv run pytest tests/test_main_auto_cache_refresh.py tests/screening/test_auto_pipeline_publication.py tests/screening/test_data_quality_manifest.py -q`
  - `185 passed in 0.80s`
- `uv run pytest tests/scripts/test_run_exit_shadow_research.py -q`
  - `54 passed in 2.03s`
- `git diff --check`
  - clean

The repository-wide bare `uv run pytest -q` remains blocked during collection
by a pre-existing unrelated mismatch: `tests/tools/test_tushare_fund_flow.py`
imports `_load_token`, which is absent from the unchanged HEAD version of
`src/tools/tushare_fund_flow.py`. A diagnostic run excluding that file reached
`161 passed, 1 skipped` before being stopped after 63 seconds because the full
repository suite is substantially broader than this branch.

## Concerns / intentional constraints

- Historical legacy journals cannot support a historical point-in-time claim
  until event append/availability timestamps exist. This is an explicit
  fail-closed limitation, not a recoverable inference.
- Direct/manual fill callers that previously requested the exact gross target
  lot (for example 1,000 shares at 10.00 for a 10%/100k plan) must request a lot
  that also leaves room for costs; production automatic sizing already does so.
- OversoldBounce remains disabled and no challenger exit is promoted by this
  fix wave.
