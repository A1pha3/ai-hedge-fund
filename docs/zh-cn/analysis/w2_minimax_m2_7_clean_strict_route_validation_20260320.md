# W2 MiniMax-M2.7 Clean Strict-Route Validation

## 1. 结论

本页记录 `2026-01-20..2026-03-13` 窗口下，`LLM_DISABLE_FALLBACK=true` 条件重新运行后的 W2 clean rerun 结果。

1. `paper_trading_window_20260120_20260313_w2_live_m2_7_clean_rerun_20260319` 已完整完成，`session_summary.json`、`daily_events.jsonl`、`pipeline_timings.jsonl` 均已落盘。
2. `session_summary.json.llm_route_provenance` 显示 `rate_limit_errors=0`、`fallback_attempts=0`、`fallback_observed=false`、`contaminated_by_provider_fallback=false`，因此这次运行可以作为“无 provider fallback 污染”的 strict-route clean evidence。
3. 这份 clean evidence 只证明默认路由没有在 runtime 中 silently 切 provider，不证明整个 session 退化成 `MiniMax-only`。本次 metrics summary 仍记录到 `Volcengine` 和 `Zhipu` 调用，说明系统里原本存在多 provider agent 路由；clean 的正确口径是“no provider fallback contamination”，不是“single-provider-only session”。
4. 因为 `MiniMax-M2.7` 相对 `MiniMax-M2.5` 的语义漂移结论没有改变，所以这份 W2 clean evidence 仍只属于 M2.7 分支验证记录，不能替换当前 M2.5 baseline。

## 2. 关键指标

| 指标 | Clean W2 数值 |
| --- | --- |
| Return | `-1.6097%` |
| Final Value | `98390.3041` |
| Sharpe | `-2.3683` |
| Sortino | `-1.9551` |
| Max Drawdown | `-2.6003%` |
| Max Drawdown Date | `2026-02-05` |
| Avg Invested | `5.9666%` |
| Peak Single Name | `14.8285%` |
| Final Cash Ratio | `81.8285%` |
| Day Count | `33` |
| Executed Trade Days | `5` |
| Total Executed Orders | `6` |
| Avg Layer-B | `2.1212` |
| Avg Watch | `0.4848` |
| Avg Buy | `0.1212` |
| Avg Day Sec | `182.73s` |

## 3. 漏斗与执行特征

1. buy blocker 以 `position_blocked_score x6` 为主，其次是 `blocked_by_exit_cooldown x5`，说明 clean rerun 的主限制回到了分数闸门与冷却并存，而不是 fallback 导致的不可比噪音。
2. watch blocker 仍主要是 `decision_avoid x50`，其次是 `score_final_below_watchlist_threshold x4`。
3. 窗口末状态为：期末组合价值 `98390.3041`，现金约 `80511.3041`，`601600` 持有 `400` 股，`300724` 持有 `100` 股。
4. `2026-03-12` 发生一次真实执行，`2026-03-13` 收尾日无执行；最后一日 `pipeline_day_timing.total_day=140.648s`，fast-agent 仍是长窗口主要耗时来源。

## 4. Provenance 解读

1. `llm_route_provenance.attempts=890`，`successes=888`，`errors=2`，错误类型来自 `ValidationError`，不是 rate limit 或 provider fallback。
2. `routes_seen` 只有 `MiniMax:default` 和 `unknown`；与 `fallback_attempts=0`、`contaminated_by_provider_fallback=false` 一起看，足以支撑“未发生 provider fallback 污染”的结论。
3. `providers_seen` / `models_seen` 中出现 `Volcengine:doubao-seed-2.0-pro` 与 `Zhipu:glm-4.7`，因此这次 run 不能表述成 `MiniMax-only`。更准确的说法是：默认模型路由 clean，session 仍保留系统原生的多 provider 使用面。

## 5. 对 W2 归档口径的影响

1. 原先的 `w2_minimax_m2_7_live_frozen_contaminated_probe_20260319.md` 仍然有效，它证明的是 contaminated live 与 frozen replay 的强一致复验。
2. 本页新增的是另一条独立证据链：在 strict-route fail-closed 条件下，W2 live 可以完整跑完且没有 provider fallback 污染。
3. 因此 W2 现在应同时保留两种归档：
   - contaminated probe：回答“污染后的 live 是否可被 frozen 强一致复验”；
   - clean strict-route validation：回答“默认路由是否能在长窗口下无 provider fallback 地完成”。
4. 两者都属于 `MiniMax-M2.7` 分支证据，不进入 M2.5 baseline 主序列。

## 6. 相关产物

1. `data/reports/paper_trading_window_20260120_20260313_w2_live_m2_7_clean_rerun_20260319/session_summary.json`
2. `data/reports/paper_trading_window_20260120_20260313_w2_live_m2_7_clean_rerun_20260319/daily_events.jsonl`
3. `data/reports/paper_trading_window_20260120_20260313_w2_live_m2_7_clean_rerun_20260319/pipeline_timings.jsonl`
4. `logs/llm_metrics_20260319_231624.summary.json`
