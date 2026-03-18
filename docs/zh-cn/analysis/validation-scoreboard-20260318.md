# 2026-03-18 Validation Scoreboard

## 1. 口径冻结

本页用于完成 P0-1，把 benchmark 守边界、长窗口 replay 结果、利用率、集中度、funnel 和主要 blocker 固定到同一张比较面板。

`baseline` 在本页中固定指向 [paper-trading-reentry-validation-20260317.md](./paper-trading-reentry-validation-20260317.md) 已明确的当前默认纸面交易基线，即 `paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317`，而不是更早的 `existing_position_fix` 或 `prod_validation`。

## 2. Benchmark Guardrail

| Guardrail | 期望行为 | 当前口径 |
| --- | --- | --- |
| `20260224 / 600519` | 应继续保持为 near-threshold 放行样本，不能重新被压回 watch 以下 | 固定参考，不在本轮长窗口 runs 中重放；继续以 [edge-sample-benchmark-20260318.md](./edge-sample-benchmark-20260318.md) 为硬边界 |
| `20260226 / 600519` | 应继续保持 near-threshold 但不过线，不能被推到明显更激进的通过区间 | 固定参考，不在本轮长窗口 runs 中重放；继续以 [edge-sample-benchmark-20260318.md](./edge-sample-benchmark-20260318.md) 为硬边界 |
| `20260226 / 300724` | watch 边缘样本不得绕过 re-entry 确认保护重新回补 | `baseline` 视为当前通过口径；`prod_validation` 明确违反该 guardrail |

## 3. Scoreboard

| Run | Source | Plan Mode | Return | Final Value | Sharpe | Max DD | Avg Invested | Peak Single Name | Avg L-B | Avg Watch | Avg Buy | Trade Days / Orders | Main Blockers | Avg Day Sec | Guardrail |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | `paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317` | `frozen_current_plan_replay` | `-0.5520%` | `99447.99` | `-1.7564` | `-1.8893%` | `14.51%` | `13.49%` | `2.29` | `0.71` | `0.24` | `5 / 6` | buy: `position_blocked_score x6`; watch: `decision_avoid x24` | `1.32s` | `PASS` 当前固定默认基线 |
| `existing_position_fix` | `paper_trading_window_20260202_20260303_existing_position_fix` | `live_pipeline` | `-2.6902%` | `97309.78` | `-4.2225` | `-3.2415%` | `18.64%` | `14.69%` | `1.63` | `0.75` | `0.19` | `2 / 3` | buy: `position_blocked_single_name x9`; watch: `decision_avoid x12` | `242.18s` | `LEGACY` 未按 benchmark 重验 |
| `exit_fix` | `paper_trading_window_20260202_20260303_exit_fix` | `live_pipeline` | `-3.9769%` | `96023.11` | `-6.7707` | `-4.0440%` | `12.77%` | `14.76%` | `1.63` | `0.75` | `0.31` | `7 / 8` | buy: `position_blocked_single_name x7`; watch: `decision_avoid x13` | `252.43s` | `LEGACY` 未按 benchmark 重验 |
| `cooldown` | `paper_trading_window_20260202_20260303_exit_fix_cooldown5` | `live_pipeline` | `-2.9036%` | `97096.40` | `-4.4654` | `-3.0787%` | `13.10%` | `14.74%` | `2.38` | `0.81` | `0.31` | `5 / 8` | buy: `position_blocked_single_name x4`, `blocked_by_exit_cooldown x3`; watch: `decision_avoid x23` | `384.64s` | `LEGACY` 未按 benchmark 重验 |
| `trading_days` | `paper_trading_window_20260202_20260304_exit_fix_cooldown5_trading_days` | `live_pipeline` | `-2.4428%` | `97557.17` | `-3.4470` | `-2.6677%` | `16.11%` | `14.74%` | `2.29` | `0.65` | `0.29` | `5 / 7` | buy: `blocked_by_exit_cooldown x3`; watch: `decision_avoid x25` | `323.34s` | `LEGACY` 未按 benchmark 重验 |
| `retrace6` | `paper_trading_window_20260202_20260304_exit_fix_cooldown5_trading_days_retrace6` | `live_pipeline` | `-2.3152%` | `97684.82` | `-3.2680` | `-2.6677%` | `15.27%` | `14.74%` | `2.29` | `0.71` | `0.29` | `6 / 8` | buy: `blocked_by_exit_cooldown x4`; watch: `decision_avoid x25` | `413.00s` | `LEGACY` 未按 benchmark 重验 |
| `prod_validation` | `paper_trading_window_20260202_20260304_prod_validation_20260317` | `live_pipeline` | `-1.2525%` | `98747.49` | `-3.0307` | `-1.8893%` | `18.05%` | `13.49%` | `2.29` | `0.71` | `0.29` | `6 / 7` | buy: `position_blocked_score x6`; watch: `decision_avoid x24` | `237.69s` | `FAIL` `20260226 / 300724` 重新回补 |

## 4. 直接结论

1. 如果把 benchmark guardrail 一起算进来，当前最稳的默认基线仍然是 `baseline`，不是 `prod_validation`。后者收益更好，但它把 `20260226 / 300724` 重新放回成交层，直接破坏了 re-entry 保护边界。
2. 在 legacy live pipeline runs 里，收益最好的阶段是 `retrace6`，但它仍然只是 `-2.3152%`，而且期末现金占比仍有 `94.08%`，低利用率问题没有被解决。
3. `existing_position_fix` 到 `exit_fix` 主要问题不是候选完全消失，而是买单阶段长期被 `position_blocked_single_name` 卡死，导致漏斗尾部和持仓结构同时变窄。
4. `cooldown`、`trading_days`、`retrace6` 把 buy blocker 主因逐步切换成 `blocked_by_exit_cooldown`，说明研究重心已经从“能不能下单”转向“退出后多久允许重进更合理”。
5. 所有 runs 的平均资金利用率都只在 `12.77%` 到 `18.64%` 之间，单票峰值权重却长期在 `13.49%` 到 `14.76%` 区间，当前主矛盾仍是低利用率和低多样性并存，而不是简单缺少一次性成交。
6. `baseline` 的日均运行时只有 `1.32s`，本质上是 frozen replay 成本，不应和 live pipeline 的 `237s` 到 `413s` 直接做同质性能比较；它更适合作为研究基线，而不是运行成本基线。

## 5. 字段定义

1. `Return`：用 `session_summary.initial_capital` 与期末 `cash + marked-to-market positions` 重算的总收益率。
2. `Final Value`：期末现金加最后一个交易日 `current_prices` 标记后的持仓市值。
3. `Avg Invested`：按 `daily_events.jsonl` 每日 `portfolio_snapshot` 和 `current_prices` 计算的平均已投资资金占比。
4. `Peak Single Name`：同一套日级 mark-to-market 口径下，窗口内最大单票权重峰值。
5. `Avg L-B / Avg Watch / Avg Buy`：来自 `current_plan.risk_metrics.counts` 的日均 `layer_b_count / watchlist_count / buy_order_count`。
6. `Main Blockers`：来自 `current_plan.risk_metrics.funnel_diagnostics.filters` 的 `watchlist` 与 `buy_orders` `reason_counts` 聚合。
7. `Avg Day Sec`：来自 `pipeline_timings.jsonl` 的 `timing_seconds.total_day` 日均值。
8. `Guardrail`：对 benchmark 口径的说明列。只有 `baseline` 与 `prod_validation` 在当前证据链里可以直接回答 re-entry guardrail 是否被破坏；其余历史 runs 只保留 legacy 参考身份。

## 6. 数据来源

1. `session_summary.json`
2. `daily_events.jsonl`
3. `pipeline_timings.jsonl`
4. [paper-trading-reentry-validation-20260317.md](./paper-trading-reentry-validation-20260317.md)
5. [edge-sample-benchmark-20260318.md](./edge-sample-benchmark-20260318.md)
6. 同目录 JSON 版本：[validation-scoreboard-20260318.json](./validation-scoreboard-20260318.json)
