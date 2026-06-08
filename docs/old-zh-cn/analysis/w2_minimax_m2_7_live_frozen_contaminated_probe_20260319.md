# W2 MiniMax-M2.7 Live / Frozen Contaminated Probe

## 1. 目标

本页用于收口 W2：记录 `2026-01-20..2026-03-13` 窗口下，`MiniMax-M2.7` live pipeline 与同窗 frozen replay 的对齐结果，并明确为什么这次运行虽然对齐强度高于 W1，仍不能升级为 clean validation。

结论先行：

1. W2 live 与 W2 frozen 在 `performance_metrics`、`daily_event_stats`、期末组合价值和最近 5 个交易日资金曲线尾段上完全一致，可视为一次强 replay 对齐。
2. 该结果不能写成 `BRANCH PASS` 或 clean validation，因为 live 运行期间已观察到 `MiniMax limited, switching to Volcengine Ark:doubao-seed-2.0-pro`，provider fallback 污染了 live run 的单一模型语义。
3. 因此 W2 的正确归档口径是 `fallback_contaminated_probe`：它证明当前 runtime 与 frozen replay 在该窗口下高度可复验，但不能证明 `MiniMax-M2.7` 单一路由本身已经稳定通过更长窗口验证。

## 2. 运行对象

| Alias | Report Dir | Plan Mode | 说明 |
| --- | --- | --- | --- |
| `w2_live_m2_7` | `data/reports/paper_trading_window_20260120_20260313_w2_live_m2_7_20260319` | `live_pipeline` | `MiniMax-M2.7` 分支的 W2 长窗口 live 探针 |
| `w2_frozen_m2_7` | `data/reports/paper_trading_window_20260120_20260313_w2_frozen_replay_m2_7_20260319` | `frozen_current_plan_replay` | 以 live `daily_events.jsonl` 为 frozen plan source 的同窗重放 |

## 3. 核心对齐项

| 项目 | Live | Frozen | 结论 |
| --- | --- | --- | --- |
| Final Value | `97177.7047` | `97177.7047` | 一致 |
| Sharpe | `-3.6660` | `-3.6660` | 一致 |
| Sortino | `-3.2530` | `-3.2530` | 一致 |
| Max Drawdown | `-2.9943%` | `-2.9943%` | 一致 |
| `daily_event_stats.day_count` | `33` | `33` | 一致 |
| `daily_event_stats.executed_trade_days` | `6` | `6` | 一致 |
| `daily_event_stats.total_executed_orders` | `7` | `7` | 一致 |
| 最近 5 个交易日 `portfolio_values` | 完全一致 | 完全一致 | 一致 |

## 4. W2 摘要指标

| 指标 | W2 数值 |
| --- | --- |
| Return | `-2.8223%` |
| Avg Invested | `7.0958%` |
| Peak Single Name | `14.8285%` |
| Final Cash Ratio | `94.2044%` |
| Avg Layer B | `2.1212` |
| Avg Watchlist | `0.4848` |
| Avg Buy Order | `0.1212` |
| Main Buy Blockers | `blocked_by_exit_cooldown x7`, `position_blocked_score x3`, `position_blocked_single_name x1` |
| Main Watch Blockers | `decision_avoid x49`, `score_final_below_watchlist_threshold x5` |
| Avg Total Day Sec | live `296.5924s`, frozen `1.3892s` |

补充观察：

1. W2 期末现金占比仍高达 `94.2044%`，说明长窗口下主矛盾依旧不是高杠杆错配，而是低利用率与低部署深度并存。
2. W2 窗口中的单票峰值发生在 `2026-02-04 / 300724`，权重约 `14.8285%`，当日单票市值 `14770.0`，组合价值 `99605.2692`。
3. live 与 frozen 的 `max_position_count` 都是 `2`，说明本轮 W2 依然没有出现持仓显著扩散。

## 5. 污染证据与严格口径

本轮 W2 最关键的限制不是 replay 对齐失败，而是 live provider 路由已经不再纯净。

已确认事实：

1. W2 live 运行过程中，终端输出多次出现 `MiniMax limited, switching to Volcengine Ark:doubao-seed-2.0-pro`。
2. 这意味着 live 结果并非由单一 `MiniMax-M2.7` provider 路由独立生成，而是混入了跨 provider fallback。
3. frozen replay 虽然完整复现了 live `daily_events.jsonl` 对应的计划与执行结果，但它复现的是“已受 fallback 污染的 live 计划”，而不是一个 clean MiniMax-only W2 run。

因此，本页的严格表述必须是：

1. W2 证明了 `fallback-contaminated live` 与 `frozen replay` 在当前 runtime 下可以强一致复验。
2. W2 不能证明 `MiniMax-M2.7` 单一路由已经在 `2026-01-20..2026-03-13` 窗口下稳定通过验证。

## 6. 运行耗时含义

1. W2 live 目录 birth time 与 summary 落盘时间之间的墙钟时长约为 `2h43m09s`。
2. `pipeline_timings.jsonl` 显示 live 的主要耗时几乎全部在 post-market 阶段，占日总耗时约 `99.51%`。
3. post-market 内部又几乎全部由 `fast_agent` 主导，占 post-market 约 `92.38%`；`score_batch` 约占 `7.18%`。
4. 这说明 W2 之前的“像是卡在数据或 checkpoint”只是表象，真实瓶颈是长窗口下 fast-agent 路径整体过慢，且 checkpoint 落盘滞后于终端进度。

## 7. 研究含义

1. W2 的对齐强度高于 W1，因为它不仅核心绩效一致，而且 `daily_event_stats` 也一致。
2. 但 W2 的证据链同时更严格地暴露了 provider fallback 污染问题，所以它在研究等级上仍低于 clean validation。
3. 当前更稳妥的动作不是机械继续扩到 W3，而是先把 W2 固化为 `fallback_contaminated_probe`，避免把“可复验”误写成“单模型已验证”。

## 8. 数据来源

1. `data/reports/paper_trading_window_20260120_20260313_w2_live_m2_7_20260319/session_summary.json`
2. `data/reports/paper_trading_window_20260120_20260313_w2_live_m2_7_20260319/daily_events.jsonl`
3. `data/reports/paper_trading_window_20260120_20260313_w2_live_m2_7_20260319/pipeline_timings.jsonl`
4. `data/reports/paper_trading_window_20260120_20260313_w2_frozen_replay_m2_7_20260319/session_summary.json`
5. `data/reports/paper_trading_window_20260120_20260313_w2_frozen_replay_m2_7_20260319/daily_events.jsonl`
6. `data/reports/paper_trading_window_20260120_20260313_w2_frozen_replay_m2_7_20260319/pipeline_timings.jsonl`
