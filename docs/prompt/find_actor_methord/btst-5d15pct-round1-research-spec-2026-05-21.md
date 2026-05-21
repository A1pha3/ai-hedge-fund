# btst-5d15pct-round1-research-spec-2026-05-21

## 1. Scope
- Round 1 only covers three event prototypes:
  1. `trend_continuation`
  2. `breakout_ignition`
  3. `volume_quality_release`
- Round 1 only covers three factor families:
  1. `trend_family`
  2. `breakout_family`
  3. `volume_quality_family`
- Round 1 only allows two second-order interactions:
  1. `trend_x_close_strength`
  2. `breakout_x_volume_quality`

## 2. Entry and outcome labels
- Signal day = `T`
- Entry proxy = `T+1` executable open proxy
- Main success label:
  - `future_high_hit_15pct_2_5d = True`
  - derived from `extract_btst_price_outcome()`
- Secondary labels:
  - `max_future_high_return_2_5d`
  - `time_to_hit_15pct`
  - `next_open_return`
  - `entry_day_liquidity_pass`
- Beta execution proxy:
  - `entry_day_liquidity_pass = True` when next-open data exists and the row is not impossible-fill
  - `gap_within_band = True` when `next_open_return <= 0.03`

## 3. Round-1 prototype definitions

### `trend_continuation`
- `trend_acceleration >= 0.55`
- `close_strength >= 0.60`

### `breakout_ignition`
- `breakout_freshness >= 0.55`
- `volume_expansion_quality >= 0.55`

### `volume_quality_release`
- `volume_expansion_quality >= 0.60`
- `close_strength >= 0.55`
- `breakout_freshness < 0.55`

## 4. Round-1 factor family formulas
- `trend_family = mean(trend_acceleration, close_strength, trend_continuation_or_reversal_flip)`
- `breakout_family = mean(breakout_freshness, close_strength, breakout_volume_alignment)`
- `volume_quality_family = mean(volume_expansion_quality, t0_tail_strength, close_strength)`

## 5. Round-1 gate contract

### Alpha gate
- `closed_cycle_count >= 3`
- `future_high_hit_15pct_2_5d_hit_rate >= 0.55`
- `mean_max_future_high_return_2_5d >= 0.15`

### Beta gate
- `beta_tradeable_rate >= 0.70`
- `mean_next_open_return <= 0.03`

### Gamma gate
- `unique_report_dir_count >= 2`
- no single report dir contributes more than 70% of closed-cycle hits

### Promotion rule
- only candidates passing alpha, beta, and gamma enter the round-1 shortlist

## 6. Outputs
- JSON artifact path
- Markdown artifact path
- candidate-pack doc path

## 7. Next Actions
- shortlist-only follow-up
- do not widen prototype/family scope in round 2 until round 1 shortlist is reviewed
