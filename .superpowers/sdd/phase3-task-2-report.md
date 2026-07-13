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
- Setup, regime, and source labels/counters kept separate.
- Current board-rule mismatch and board-rule auditability recorded independently; mismatches
  remain in the legacy sensitivity cohort.
- Recorded journal return versus reconstructable legacy T+10 close return audited per trade.
- `audit_coverage()` preserves the paired denominator, compares covered and missing legacy
  groups, warns on selection bias, and permanently reports `production_eligible=False`.

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
   receives that reconstructed value and the focused suite passes 8/8.

## Fresh verification

- `git diff --check` — passed.
- `uv run ruff check src/research/exit_shadow_research.py tests/research/test_exit_shadow_research.py` — passed.
- `uv run pytest tests/research/ tests/offensive/ -q` — 647 passed.

## Real-data read-only smoke audit

Using the 403-row backtest journal and the available 626-file parent price cache:

- unique paired BTST keys: 133;
- reconstructable/execution-eligible paths: 94 (coverage 70.6767%);
- paired paths missing a ticker price file: 39;
- unmatched BTST BUY keys: 13 (excluded outside the paired denominator);
- current-board-rule mismatches among included paths: 47;
- recorded-versus-reconstructable return mismatches: 55;
- covered legacy mean: +9.9866%; missing legacy mean: +3.7110%;
- selection-bias warning: true; production eligible: false.

These mismatch counts are audit disclosures, not evidence for parameter selection or production
promotion. The legacy sample remains sensitivity-only.

## Self-review concerns

- The checked-out worktree contains only one tracked price-cache file, so the real-data smoke
  audit explicitly used the parent workspace's read-only cache path. The builder itself accepts
  an injected loader or explicit cache directory and never writes either location.
- A board-rule mismatch can be computed only when `pct_change` exists or a prior close is
  available. Such paths expose `board_rule_auditable=False` instead of inventing a mismatch.
- The reconstructed legacy return uses the journal BUY `entry_price` when valid and session-10
  close, matching the historical paper-tracker P&L convention. The recorded value is rounded to
  two percentage decimals, so comparison uses a 1.5 bp return-unit tolerance.
