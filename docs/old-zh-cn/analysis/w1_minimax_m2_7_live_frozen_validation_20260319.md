# W1 MiniMax-M2.7 Live / Frozen Validation

## 1. 目标

本页用于收口 W1：验证 `2026-02-02..2026-03-13` 窗口下，`MiniMax-M2.7` live pipeline 与 frozen current-plan replay 是否在研究所需的核心结论层面保持一致，并明确一致性的边界。

结论先行：

1. W1 live 与 W1 frozen 在资金曲线、核心绩效、最终持仓、关键交易/约束事件上对齐，可以视为 `MiniMax-M2.7` 分支上的一次有效 replay 验证。
2. 该结论不能表述为“summary 全字段一致”。两者 `session_summary.json` 中的 `daily_event_stats` 不一致，说明 replay 层与 live 层在摘要聚合口径上仍有差异。
3. 该 W1 结果只作为 `MiniMax-M2.7` 分支验证记录，不替代当前 `MiniMax-M2.5` baseline，也不并入主表横向基线结论。

## 2. 运行对象

| Alias | Report Dir | Plan Mode | 说明 |
| --- | --- | --- | --- |
| `w1_live_m2_7` | `data/reports/paper_trading_window_20260202_20260313_w1_live_m2_7_20260319` | `live_pipeline` | 使用 `MiniMax-M2.7` 完整跑过窗口 |
| `w1_frozen_m2_7` | `data/reports/paper_trading_window_20260202_20260313_w1_frozen_replay_m2_7_20260319` | `frozen_current_plan_replay` | 以 live `daily_events.jsonl` 作为 frozen plan source 的重放 |

## 3. 核心对齐项

| 项目 | Live | Frozen | 结论 |
| --- | --- | --- | --- |
| Final Value | `99523.9516` | `99523.9516` | 一致 |
| Sharpe | `-1.4300` | `-1.4300` | 一致 |
| Max Drawdown | `-1.4966%` | `-1.4966%` | 一致 |
| 期末持仓 | `601600` 多头 `400` 股 | `601600` 多头 `400` 股 | 一致 |
| 关键退出 | `603993` 于 `20260303` 已退出 | 同步反映 | 一致 |
| 关键约束 | `300724` 于 `20260226` hard stop loss 后保留 `blocked_until=20260305`、`reentry_review_until=20260312` | 同步反映 | 一致 |

## 4. 非一致项与严格口径

以下差异必须显式保留，不能被“整体一致”表述吞掉：

| 字段 | Live | Frozen | 说明 |
| --- | --- | --- | --- |
| `daily_event_stats.day_count` | `13` | `24` | frozen 摘要聚合口径与 live 不同 |
| `daily_event_stats.executed_trade_days` | `2` | `5` | 不能宣称 summary 全字段一致 |
| `daily_event_stats.total_executed_orders` | `2` | `6` | 不能把 replay 摘要直接当作 live 摘要复刻 |
| `avg_total_day_seconds` | `177.41s` | `1.14s` | replay 运行成本天然更低，只能作为回放验证，不可与 live 成本同质比较 |

因此，本轮 W1 的正确口径是：

1. `MiniMax-M2.7` live 与 frozen 在研究所关心的交易结果层面已经对齐。
2. `session_summary.json` 的部分聚合字段仍存在 live / replay 差异，需要后续单独解释或修正。

## 5. 关键证据

1. 两份 `session_summary.json` 的 `performance_metrics` 与 `portfolio_values` 末值一致。
2. 两份 `daily_events.jsonl` 在 `20260306`、`20260309` 等日期都保留了 `300724` 的 exit / re-entry cooldown 约束，且字段一致地显示：
   - `trigger_reason=hard_stop_loss`
   - `exit_trade_date=20260226`
   - `blocked_until=20260305`
   - `reentry_review_until=20260312`
3. live `session_summary.json` 明确显示 `last_trade_date=20260313`，且最终仅剩 `601600` 多头 `400` 股。
4. frozen `plan_generation.frozen_plan_source` 直接指向 live `daily_events.jsonl`，符合“先 live，再 frozen replay 对照”的证据链。

## 6. 研究含义

1. `MiniMax-M2.7` 已经具备在当前 runtime / guardrail 下做 live-to-frozen 验证的最小可重复性。
2. 这不意味着 `MiniMax-M2.7` 可直接替换当前 `MiniMax-M2.5` baseline；前序 benchmark 已确认 M2.7 相对 M2.5 存在语义漂移，因此仍需保持分支记录。
3. 如果后续进入 W2，应以本页作为 W1 完成证明，但不能忽略 `daily_event_stats` 的聚合差异。

## 7. 数据来源

1. `data/reports/paper_trading_window_20260202_20260313_w1_live_m2_7_20260319/session_summary.json`
2. `data/reports/paper_trading_window_20260202_20260313_w1_live_m2_7_20260319/daily_events.jsonl`
3. `data/reports/paper_trading_window_20260202_20260313_w1_live_m2_7_20260319/pipeline_timings.jsonl`
4. `data/reports/paper_trading_window_20260202_20260313_w1_frozen_replay_m2_7_20260319/session_summary.json`
5. `data/reports/paper_trading_window_20260202_20260313_w1_frozen_replay_m2_7_20260319/daily_events.jsonl`
6. `data/reports/paper_trading_window_20260202_20260313_w1_frozen_replay_m2_7_20260319/pipeline_timings.jsonl`
