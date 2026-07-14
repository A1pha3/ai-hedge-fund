# Phase 3 Task 4 Report — Time-block sensitivity statistics

## Status

Implemented deterministic, block-aware sensitivity summaries over the approved paired
common mask. The output is permanently shadow-only and cannot claim production eligibility.
No exit parameter search, portfolio Sharpe, drawdown, or production switch was added.

## Delivered

- `PairedReplayRow` preserves immutable common-key baseline/challenger pairing and carries the
  sorted union of all actual trading sessions supplied by the replay paths.
- `moving_block_mean_difference()` first equal-weights trade differences within signal date,
  then constructs moving windows from 10 consecutive entries of the real supplied-session
  calendar. For every draw it samples non-empty blocks with replacement until it has at least
  the original signal-day count, then deterministically truncates to that exact count. It
  reports the 95% percentile interval plus candidate, usable, empty, sampled-block, and
  effective-sample counts.
- Empty input, fewer than two signal dates, fewer than 10 real sessions, fewer than two usable
  blocks, block lengths below T+10, non-positive draws, malformed dates, duplicate trade keys,
  and non-finite returns fail closed.
- `summarize_paired_results()` reports trade and signal-day counts, maximum-cardinality
  non-overlapping signal-to-latest-exit windows, equal-signal-day-weighted paired
  mean/median/worst-decile/downside-tail differences,
  per-arm mean/median/tail returns, holding sessions, exit reasons, coverage, and covered versus
  missing-group legacy means.
- Replay rows retain actual holding sessions and a causal MFE diagnostic: held-session daily
  highs only through the last close before exit, plus the actual exit open. The exit session's
  high/low/close are never used. Daily highs are explicitly marked non-executable.
  `give_up = MFE - net_return` is reported
  wherever MFE is valid. MFE capture is reported only for positive MFE and only when the fixed,
  pre-registered `MIN_POSITIVE_MFE_COUNT = 10` denominator is met.
- The summary enforces `shadow_only=True` and `production_eligible=False`.

## TDD evidence

1. Required RED: the focused module failed collection because `PairedReplayRow` and the block
   statistics interfaces did not exist.
2. Initial GREEN: the complete focused module reached **80 passed**.
3. Calendar self-review RED: an early challenger exit truncated its calendar and the dedicated
   regression failed. The replay now carries every supplied path session; focused reached
   **81 passed**.
4. MFE RED: the audited-high diagnostic regression failed against a deliberately absent MFE,
   then passed after restoring path-derived MFE and holding-session calculation.
5. Additional signal-day aggregation and sparse/empty-block coverage brought the focused module
   to **84 passed**.
6. Review-fix RED covered fixed bootstrap sample size, unequal same-day clusters, causal MFE,
   duplicate/reversed/inconsistent calendars, and maximum interval scheduling. All failed on
   the prior implementation and passed after the fixes; focused is now **93 passed**.
7. Research plus offensive verification: **736 passed**.

## Real-data read-only audit

Read only the parent workspace's `data/paper_trading_backtest/journal.jsonl` and 626-file
`data/price_cache`; did not use the runtime `data/paper_trading/` instance and did not mutate
either source. Costs used the production-named `ExecutionCosts(version="daily-action-v2")`
defaults. Bootstrap used 10,000 draws, 10 sessions per block, seed 0.

- paired BTST denominator: **133**;
- reconstructable Task 2 paths: **94**;
- executable common mask: **79** (**59.3985%** of paired denominator);
- unique signal days: **36**;
- supplied real-session calendar: **103 sessions**;
- greedy non-overlapping signal-to-latest-exit windows: **7**;
- moving blocks: **94 candidate / 86 usable / 8 empty**;
- covered/missing legacy means: **+8.6144% / +7.4617%** (valid recorded returns only for the
  missing mean; invalid/unclassified returns remain in the 133 denominator);
- baseline/challenger mean net return: **+5.1721% / +5.1721%**;
- paired mean / median / worst decile: **0.0000% / 0.0000% / 0.0000%**;
- 95% moving-block interval for mean paired difference: **[0.0000%, 0.0000%]**;
- baseline/challenger mean holding: **10.0506 / 10.0506 sessions** (deferred exits can exceed
  session 10);
- challenger exit reasons: **79 maximum_holding_session**;
- every one of the 10,000 bootstrap draws has exactly **36** effective signal-day observations;
  sampled blocks per draw range from **6 to 15** because block density varies;
- challenger positive-MFE diagnostic denominator: **79**; mean capture ratio **-0.6026** and
  mean give-up **11.1181 percentage points**. The capture value can be negative because a trade
  may finish negative despite a positive, non-executable daily-high MFE.

The zero paired distribution is not evidence of improvement or equivalence. It only shows that
the fixed challenger took the same executable exit as the baseline for every row in this limited,
selected, six-month legacy common mask.

## Concerns

- Only seven greedy non-overlapping windows remain after respecting actual holding overlap.
- The common mask is selected and materially smaller than the 133-trade denominator; coverage
  and missing-group statistics must remain beside every result.
- MFE uses daily highs solely as path diagnostics; it is not a realizable fill series.
- No production configuration or daily-action execution behavior changed.
