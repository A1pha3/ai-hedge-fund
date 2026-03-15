# Tune Layer C P1 Defaults And Validate 600519 Live Replay

## Summary

This change finalizes the current P1 candidate by keeping the scope limited to Layer C and watchlist tuning rather than further expanding Layer B.

- change Layer C blend defaults to 0.55/0.45
- apply investor cohort scale 0.90 before normalization
- lower default watchlist threshold to 0.20
- keep avoid threshold at -0.30
- add resumable 600519 live replay, summary, and doc update scripts

## Why

Previous end-to-end backtests showed that Layer B rule variants increased mid-funnel volume but did not change realized orders or returns. Focused replay then showed that most extra names were suppressed by investor-cohort drag at Layer C, while 600519 behaved like a threshold-edge case.

This change therefore avoids further Layer B expansion and instead makes a minimal Layer C plus watchlist adjustment intended to release only edge candidates while keeping structurally negative names blocked.

## Validation

- execution tests: `pytest tests/execution/test_phase4_execution.py -q` => `32 passed`
- offline business regression keeps 8 structural-conflict samples blocked
- live replay `20260224 / 600519`: `score_final = 0.2158`, crosses the 0.20 watchlist threshold
- live replay `20260226 / 600519`: `score_final = 0.1962`, remains edge-like and does not cross 0.20

## Residual Risk

- live replay coverage is still limited to the two 600519 target dates
- broader-window validation is still pending
- occasional upstream data instability may still affect replay runs

## Review Guidance

- treat this as a minimal Layer C plus watchlist calibration, not a Layer B expansion
- verify that the default behavior still blocks structurally negative conflict samples
- use the 600519 live replay result as the smallest business-level confirmation for P1
