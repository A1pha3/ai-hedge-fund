# Short Trade Boundary Builder Live Validation Window Summary

## Scope

- Baseline report: `data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329`
- New live builder reports:
  - `data/reports/paper_trading_window_20260323_20260326_live_m2_7_dual_target_boundary_builder_validation_20260329` for `2026-03-23,2026-03-24`
  - `data/reports/paper_trading_20260325_20260325_live_m2_7_dual_target_boundary_builder_validation_20260329`
  - `data/reports/paper_trading_20260326_20260326_live_m2_7_dual_target_boundary_builder_validation_20260329`

## Day-Level Comparison

| trade_date | baseline short_trade_target_count | baseline layer_b_boundary score-fail | baseline boundary mean score_target | new short_trade_target_count | new layer_b_boundary score-fail | new short_trade_boundary near_miss | new boundary mean score_target |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-03-23,2026-03-24 | 14 | 11 | 0.1469 | 5 | 0 | 2 | 0.5487 |
| 2026-03-25 | 9 | 6 | 0.1346 | 5 | 0 | 2 | 0.5579 |
| 2026-03-26 | 9 | 6 | 0.1030 | 5 | 0 | 2 | 0.5372 |

## Window Totals

- Baseline short-trade targets across `2026-03-23~2026-03-26`: `32`
- New live builder short-trade targets across `2026-03-23~2026-03-26`: `15`
- Baseline `layer_b_boundary` score-fail cluster across the window: `23`
- New live builder `layer_b_boundary` score-fail cluster across the window: `0`
- New live builder `short_trade_boundary` near-miss count across the window: `6`

## Conclusion

- The old shared Layer B boundary pool was the dominant failure cluster across the full 4-day window.
- After switching short trade to an independent boundary candidate builder, that cluster disappeared on every validated live day.
- The surviving supplemental candidates were no longer low-quality `layer_b_boundary` rejects; they became `short_trade_boundary` near-miss candidates with score quality consistently above `0.53`.
- The remaining primary bottleneck is now the `layer_c_bearish_conflict` blocked cluster rather than boundary candidate quality collapse.