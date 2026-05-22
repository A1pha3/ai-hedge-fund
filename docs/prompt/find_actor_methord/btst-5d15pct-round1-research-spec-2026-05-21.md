# BTST 5日15% 首轮研究规范（2026-05-21）

本文用于锁定首轮研究范围、标签口径与晋级门槛，避免研究过程中出现范围漂移。

## 1. 研究范围
- 首轮仅覆盖三类事件原型：
  1. `trend_continuation`
  2. `breakout_ignition`
  3. `volume_quality_release`
- 首轮仅覆盖三类因子家族：
  1. `trend_family`
  2. `breakout_family`
  3. `volume_quality_family`
- 首轮仅允许两类二阶交互：
  1. `trend_x_close_strength`
  2. `breakout_x_volume_quality`

## 2. 入场与结果标签
- 信号日记为 `T`
- 入场代理定义为 `T+1` 可执行开盘价代理
- 主成功标签：
  - `future_high_hit_15pct_2_5d = True`
  - 由 `extract_btst_price_outcome()` 派生
- 次级标签：
  - `max_future_high_return_2_5d`
  - `time_to_hit_15pct`
  - `next_open_return`
  - `entry_day_liquidity_pass`
- Beta 执行代理约束：
  - 当次日开盘数据存在且样本不属于 impossible-fill 时，`entry_day_liquidity_pass = True`
  - 当 `next_open_return <= 0.03` 时，`gap_within_band = True`

## 3. 首轮原型定义

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

## 4. 首轮因子家族公式
- `trend_family = mean(trend_acceleration, close_strength, trend_continuation_or_reversal_flip)`
- `breakout_family = mean(breakout_freshness, close_strength, breakout_volume_alignment)`
- `volume_quality_family = mean(volume_expansion_quality, t0_tail_strength, close_strength)`

## 5. 首轮门槛契约

### Alpha 门
- `closed_cycle_count >= 3`
- `future_high_hit_15pct_2_5d_hit_rate >= 0.55`
- `mean_max_future_high_return_2_5d >= 0.15`

### Beta 门
- `beta_tradeable_rate >= 0.70`
- `mean_next_open_return <= 0.03`

### Gamma 门
- `unique_report_dir_count >= 2`
- 单个报告目录（report dir）的闭环命中贡献占比不得超过 70%

### 晋级规则
- 只有同时通过 Alpha、Beta、Gamma 的候选，才可进入首轮短名单（shortlist）。

## 6. 输出产物
- JSON 产物路径
- Markdown 产物路径
- 候选包文档路径

## 7. 后续动作
- 仅围绕短名单（shortlist）继续跟进。
- 在首轮短名单（shortlist）完成评审前，不得在第二轮扩大原型或家族范围。
