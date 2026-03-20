# 2026-03-18 Validation Scoreboard

## 1. 口径冻结

本页用于完成 P0-1，把 benchmark 守边界、长窗口 replay 结果、利用率、集中度、funnel 和主要 blocker 固定到同一张比较面板。

`baseline` 在本页中固定指向 [paper-trading-reentry-validation-20260317.md](./paper-trading-reentry-validation-20260317.md) 已明确的当前默认纸面交易基线，即 `paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317`，而不是更早的 `existing_position_fix` 或 `prod_validation`。

`MiniMax-M2.7` 的 W1 / W2 结果从本次开始纳入本页，但只作为分支验证记录，用于回答“新模型分支是否具备 live-to-frozen 可复验性”。它们不替代当前 `baseline`，也不参与 M2.5 主基线优先级排序。W2 目前同时保留两条证据：一条是 contaminated probe，回答污染 live 是否可 replay；另一条是 strict-route clean rerun，回答默认路由是否能在长窗口下无 provider fallback 污染地完成。两者都不等于 M2.5 baseline 替换条件。

`single-provider-only session` 也已从本次开始有分级实测证据，当前已完成 `2026-02-02` 单日 probe、`2026-02-02..2026-02-03` 两日 rerun、`2026-02-02..2026-02-06` 五日 rerun 和 `2026-02-02..2026-02-10` extended-window rerun。它回答的是“在全局 route allowlist + fallback 禁用下，session 级 provider 使用面是否会收敛为单 provider”，不回答收益质量，也不替代 W1/W2 长窗口分支记录。

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
| `w1_m2_7_live` | `paper_trading_window_20260202_20260313_w1_live_m2_7_20260319` | `live_pipeline` | `-0.4760%` | `99523.95` | `-1.4300` | `-1.4966%` | `14.00%` | `13.44%` | `2.08` | `0.62` | `0.17` | `2 / 2` | buy: `position_blocked_score x5`; watch: `decision_avoid x32` | `177.41s` | `BRANCH PASS` W1 live 结果成立，但仅用于 M2.7 分支 |
| `w1_m2_7_frozen` | `paper_trading_window_20260202_20260313_w1_frozen_replay_m2_7_20260319` | `frozen_current_plan_replay` | `-0.4760%` | `99523.95` | `-1.4300` | `-1.4966%` | `14.00%` | `13.44%` | `2.08` | `0.62` | `0.17` | `5 / 6` | buy: `position_blocked_score x15`; watch: `decision_avoid x96` | `1.14s` | `BRANCH PASS` 核心结果对齐，但 `daily_event_stats` 与 live 不一致 |
| `w2_m2_7_live` | `paper_trading_window_20260120_20260313_w2_live_m2_7_20260319` | `live_pipeline` | `-2.8223%` | `97177.70` | `-3.6660` | `-2.9943%` | `7.10%` | `14.83%` | `2.12` | `0.48` | `0.12` | `6 / 7` | buy: `blocked_by_exit_cooldown x7`; watch: `decision_avoid x49` | `296.59s` | `BRANCH CONTAMINATED` live / frozen 强一致，但 live 期间出现跨 provider fallback |
| `w2_m2_7_frozen` | `paper_trading_window_20260120_20260313_w2_frozen_replay_m2_7_20260319` | `frozen_current_plan_replay` | `-2.8223%` | `97177.70` | `-3.6660` | `-2.9943%` | `7.10%` | `14.83%` | `2.12` | `0.48` | `0.12` | `6 / 7` | buy: `blocked_by_exit_cooldown x7`; watch: `decision_avoid x49` | `1.39s` | `BRANCH CONTAMINATED` replay 复现的是 fallback-contaminated live 计划，而非 clean MiniMax-only W2 |
| `w2_m2_7_clean_rerun` | `paper_trading_window_20260120_20260313_w2_live_m2_7_clean_rerun_20260319` | `live_pipeline` | `-1.6097%` | `98390.30` | `-2.3683` | `-2.6003%` | `5.97%` | `14.83%` | `2.12` | `0.48` | `0.12` | `5 / 6` | buy: `position_blocked_score x6`, `blocked_by_exit_cooldown x5`; watch: `decision_avoid x50` | `182.73s` | `BRANCH PASS` 无 provider fallback 污染；但这是 strict default-route clean，不等于全 session MiniMax-only |

## 4. 直接结论

1. 如果把 benchmark guardrail 一起算进来，当前最稳的默认基线仍然是 `baseline`，不是 `prod_validation`。后者收益更好，但它把 `20260226 / 300724` 重新放回成交层，直接破坏了 re-entry 保护边界。
2. 在 legacy live pipeline runs 里，收益最好的阶段是 `retrace6`，但它仍然只是 `-2.3152%`，而且期末现金占比仍有 `94.08%`，低利用率问题没有被解决。
3. `existing_position_fix` 到 `exit_fix` 主要问题不是候选完全消失，而是买单阶段长期被 `position_blocked_single_name` 卡死，导致漏斗尾部和持仓结构同时变窄。
4. `cooldown`、`trading_days`、`retrace6` 把 buy blocker 主因逐步切换成 `blocked_by_exit_cooldown`，说明研究重心已经从“能不能下单”转向“退出后多久允许重进更合理”。
5. 所有 runs 的平均资金利用率都只在 `12.77%` 到 `18.64%` 之间，单票峰值权重却长期在 `13.49%` 到 `14.76%` 区间，当前主矛盾仍是低利用率和低多样性并存，而不是简单缺少一次性成交。
6. `baseline` 的日均运行时只有 `1.32s`，本质上是 frozen replay 成本，不应和 live pipeline 的 `237s` 到 `413s` 直接做同质性能比较；它更适合作为研究基线，而不是运行成本基线。
7. `w1_m2_7_live` 与 `w1_m2_7_frozen` 已证明 `MiniMax-M2.7` 分支在资金曲线、核心绩效、最终持仓和关键约束事件上可以 replay 对齐，但 `daily_event_stats` 并未全字段一致，因此只能写成“核心结果一致”，不能写成“summary 完全一致”。
8. 因为 benchmark 已确认 `MiniMax-M2.7` 相对 `MiniMax-M2.5` 存在语义漂移，W1 只能视为新模型分支验证通过，不改变当前 `baseline` 仍由 `MiniMax-M2.5` 锁定的事实。
9. `w2_m2_7_live` 与 `w2_m2_7_frozen` 的对齐强度高于 W1，已经达到 `performance_metrics` 与 `daily_event_stats` 同时一致，但 live 运行期间发生 provider fallback，因此这组结果仍然只能归档为 `fallback_contaminated_probe`。
10. `w2_m2_7_clean_rerun` 进一步证明：在 `LLM_DISABLE_FALLBACK=true` 条件下，默认路由可以在同一长窗口内无 provider fallback 污染地完整跑完；这条证据应表述为 strict-route clean，而不是 `MiniMax-only session`。
11. clean rerun 的结果优于 contaminated W2，但仍是分支证据，不能覆盖 `MiniMax-M2.7` 对 `MiniMax-M2.5` 的语义漂移事实，也不能替换当前 baseline。
12. W2 继续说明当前长窗口主矛盾仍是低利用率和低部署深度并存：clean rerun 平均资金利用率只有 `5.97%`，虽期末现金占比已降到 `81.83%`，但部署深度仍偏低。
13. `paper_trading_probe_20260202_single_provider_m2_7_20260320`、`paper_trading_probe_20260202_20260203_single_provider_m2_7_rerun_20260320` 与 `paper_trading_probe_20260202_20260206_single_provider_m2_7_rerun_20260320` 进一步把 provider 隔离验证往前推了一步：三者分别给出 `attempts=49/99/138`、`fallback_attempts=0/0/0`、`providers_seen=["MiniMax"]` 与 `routes_seen=["MiniMax:default"]`，说明 whole-session single-provider routing 已在 `1d + 2d + 5d` 窗口下成立。
14. 这条 single-provider 验证线仍然是路由隔离 artifact，不应与 W1/W2 的收益比较混为一谈；它当前最直接的价值是证明 session 级 provider 变量已经可被独立隔离，而不是改变主 scoreboard 的 baseline 排位。
15. `paper_trading_probe_20260202_20260210_single_provider_m2_7_rerun_20260320` 进一步把该结论扩到 `7` 个交易日：`fallback_attempts=0`、`providers_seen=["MiniMax"]`、`routes_seen=["MiniMax:default"]` 继续成立，但同时出现 `attempts=325`、`successes=142`、`errors=183`、`rate_limit_errors=23`，因此它应归档为“single-provider provenance pass, stability pressured”，而不是“高稳定度 clean extended run”。

## 5. 字段定义

1. `Return`：用 `session_summary.initial_capital` 与期末 `cash + marked-to-market positions` 重算的总收益率。
2. `Final Value`：期末现金加最后一个交易日 `current_prices` 标记后的持仓市值。
3. `Avg Invested`：按 `daily_events.jsonl` 每日 `portfolio_snapshot` 和 `current_prices` 计算的平均已投资资金占比。
4. `Peak Single Name`：同一套日级 mark-to-market 口径下，窗口内最大单票权重峰值。
5. `Avg L-B / Avg Watch / Avg Buy`：来自 `current_plan.risk_metrics.counts` 的日均 `layer_b_count / watchlist_count / buy_order_count`。
6. `Main Blockers`：来自 `current_plan.risk_metrics.funnel_diagnostics.filters` 的 `watchlist` 与 `buy_orders` `reason_counts` 聚合。
7. `Avg Day Sec`：来自 `pipeline_timings.jsonl` 的 `timing_seconds.total_day` 日均值。
8. `Guardrail`：对 benchmark 口径的说明列。只有 `baseline` 与 `prod_validation` 在当前证据链里可以直接回答 re-entry guardrail 是否被破坏；其余历史 runs 只保留 legacy 参考身份。
9. `w1_m2_7_live / w1_m2_7_frozen`：M2.7 分支验证行。允许回答“live-to-frozen 的核心结果是否可复验”，但不应用于替换 M2.5 baseline 的默认位次。
10. `w2_m2_7_live / w2_m2_7_frozen`：M2.7 的更长窗口 contaminated 分支记录。允许回答“W2 contaminated live 是否可强一致 replay”，但不能并入 clean validation 主序列。
11. `w2_m2_7_clean_rerun`：M2.7 的 strict-route clean 分支记录。允许回答“默认路由是否在 W2 长窗口内无 provider fallback 污染地完成”，但不等于整个 session 没有其它 provider，也不能替换 M2.5 baseline。
12. `single_provider_probe`：用于回答“session 级 provider 使用面是否已收敛为单 provider”；它是路由隔离证据，不是收益质量证据。

## 6. 数据来源

1. `session_summary.json`
2. `daily_events.jsonl`
3. `pipeline_timings.jsonl`
4. [paper-trading-reentry-validation-20260317.md](./paper-trading-reentry-validation-20260317.md)
5. [edge-sample-benchmark-20260318.md](./edge-sample-benchmark-20260318.md)
6. 同目录 JSON 版本：[validation-scoreboard-20260318.json](./validation-scoreboard-20260318.json)
7. [w1_minimax_m2_7_live_frozen_validation_20260319.md](./w1_minimax_m2_7_live_frozen_validation_20260319.md)
8. [w2_minimax_m2_7_live_frozen_contaminated_probe_20260319.md](./w2_minimax_m2_7_live_frozen_contaminated_probe_20260319.md)
9. [w2_minimax_m2_7_clean_strict_route_validation_20260320.md](./w2_minimax_m2_7_clean_strict_route_validation_20260320.md)
10. [single-provider-session-probe-20260320.md](./single-provider-session-probe-20260320.md)
