# Phase 3 Task 2 Report — Legacy cohort builder and mismatch audit

## Status

Implemented the deterministic legacy BTST cohort builder and coverage audit from the real
`data/paper_trading_backtest/journal.jsonl` contract. No legacy journal or price-cache file
was modified.

## Delivered

- `LegacySession`, `LegacyTradePath`, `CohortExclusion`, `CoverageAudit`, and `LegacyCohort`.
- `build_legacy_cohort()` with explicit counters for journal rows, unique paired BTST keys,
  price presence, signal-date presence, complete post-signal session-10 windows, and
  execution-proxy eligibility.
- Deterministic natural-key ordering and fail-closed exclusions for malformed JSON/records,
  invalid keys or returns, duplicate BUY/EXIT events, unmatched BUY/EXIT events, missing or
  invalid price data, missing signal dates, incomplete windows, and execution-proxy failures.
- Physical journal line numbers survive pairing and every downstream exclusion. Unique pairing
  fixes the denominator before checking that EXIT occurs strictly after BUY.
- Natural keys require real `YYYYMMDD` dates and exactly six ASCII ticker digits. BTST actions
  are exact `BUY`/`EXIT`, and any supplied horizon/time-exit field must represent T+10.
- Price loading distinguishes absent, empty, unreadable, and invalid results. Session timestamps
  become civil dates before duplicate detection/sorting, and impossible OHLC bars fail closed.
  The date parser accepts only compact `YYYYMMDD`, ISO civil date/timestamp strings, and actual
  `date`/`datetime` objects; nulls, NaT/NaN, bools, numerics, and malformed strings are rejected
  as `price_data_invalid` without escaping exceptions.
- Setup, regime, and source labels/counters kept separate.
- Current board-rule mismatch and board-rule auditability recorded independently; mismatches
  compare the legacy 9.5% detector with the current ticker-specific detector and remain in the
  legacy sensitivity cohort.
- Recorded journal return versus reconstructable legacy T+10 close return audited per trade.
  Nullable `recorded_entry_price` is never replaced by session-1 open; `replay_entry_price`
  separately and explicitly carries session-1 open for Task 3.
- `audit_coverage()` preserves the paired denominator, compares covered and missing legacy
  groups, warns on selection bias, and permanently reports `production_eligible=False`. A valid
  recorded return is parsed immediately after unique pairing and remains attached to order or
  horizon exclusions; invalid returns stay unclassified without shrinking the denominator.

## TDD evidence

1. Initial focused test run failed during collection with
   `ModuleNotFoundError: src.research.exit_shadow_research`.
2. Minimal implementation turned the initial six tests green.
3. Self-review added a denominator regression test; it failed because an invalid realized
   marker reduced `total_paired_btst` from 1 to 0.
4. The implementation was corrected so unique BUY/EXIT pairing fixes the denominator before
   return parsing.
5. Staged-diff review added a missing-`pct_change` execution-proxy regression; it failed because
   a reconstructable signal return was not forwarded to the shared limit-up proxy. The proxy now
   receives that reconstructed value.
6. Review remediation added separate RED→GREEN cycles for line ordering/positions (2 tests),
   civil-date duplicates (2), loader/OHLC layers (7), natural/event/holding schema (9), exact
   rounding boundary (2), and entry-price provenance (7, including bool/string schema cases). A
   final self-review RED→GREEN also carried pair line numbers through downstream price/window
   exclusions and verified detector-to-detector mismatch semantics.
7. Final remediation added an explicit price-date allowlist cycle (18 parameter cases) and a
   paired-return/missing-group cycle covering valid/invalid returns across order and horizon
   exclusions plus covered/missing means. Focused total: 59 tests.

## Fresh verification

- `git diff --check` — passed.
- `uv run ruff check src/research/exit_shadow_research.py tests/research/test_exit_shadow_research.py` — passed.
- `uv run ruff format --check src/research/exit_shadow_research.py tests/research/test_exit_shadow_research.py` — passed.
- `uv run pytest tests/research/ tests/offensive/ -q` — 698 passed.

## Real-data read-only smoke audit

Using the 403-row backtest journal and the available 626-file parent price cache:

- unique paired BTST keys: 133;
- reconstructable/execution-eligible paths: 94 (coverage 70.6767%);
- paired paths missing a ticker price file: 39;
- unmatched BTST BUY keys: 13 (excluded outside the paired denominator);
- current-board-rule mismatches among included paths: 47;
- recorded-versus-reconstructable return mismatches: 55;
- recorded-return unauditable paths: 0;
- covered legacy mean: +9.9866%; missing legacy mean: +3.7110%;
- selection-bias warning: true; production eligible: false.

These mismatch counts are audit disclosures, not evidence for parameter selection or production
promotion. Counts are unchanged from the pre-remediation smoke audit; the stricter validators did
not silently remove any of the 94 reconstructable real paths. The legacy sample remains
sensitivity-only.

## Self-review concerns

- The checked-out worktree contains only one tracked price-cache file, so the real-data smoke
  audit explicitly used the parent workspace's read-only cache path. The builder itself accepts
  an injected loader or explicit cache directory and never writes either location.
- A board-rule mismatch can be computed only when `pct_change` exists or a prior close is
  available. Such paths expose `board_rule_auditable=False` instead of inventing a mismatch.
- The reconstructed legacy return uses the journal BUY `entry_price` when valid and session-10
  close, matching the historical paper-tracker P&L convention. The recorded value is rounded to
  two percentage decimals, so comparison allows at most 0.005 percentage point (0.00005 return
  units, 0.5 bp) plus a tiny floating-point epsilon. Missing/invalid journal entry prices are
  explicitly unauditable and never substituted with the replay entry.
