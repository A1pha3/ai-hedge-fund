# Single-Provider Session Probe

## 1. 结论

截至 `2026-03-20`，`single-provider-only session` 已完成四级 probe：

1. `2026-02-02` 单日最小 probe。
2. `2026-02-02..2026-02-03` 两日 rerun。
3. `2026-02-02..2026-02-06` 五日 rerun。
4. `2026-02-02..2026-02-10` 七交易日 extended-window rerun。

四次运行都显示当前仓库新增的 session 级 provider 闸门已经成立，而且 `5d` 与 extended-window rerun 都已经不是轻量空跑：后者窗口内出现了 `3` 个真实成交日、`4` 笔已执行订单，以及跨多日延续到 `2026-02-10` 的持仓状态。

本次运行同时设置：

1. `LLM_DEFAULT_MODEL_PROVIDER=MiniMax`
2. `LLM_DEFAULT_MODEL_NAME=MiniMax-M2.7`
3. `MINIMAX_MODEL=MiniMax-M2.7`
4. `LLM_DISABLE_FALLBACK=true`
5. `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax`

四次 probe 的 `session_summary.json.llm_route_provenance` 都显示：

1. `fallback_attempts=0`
2. `contaminated_by_provider_fallback=false`
3. `providers_seen=["MiniMax"]`
4. `models_seen=["MiniMax:MiniMax-M2.7"]`
5. `routes_seen=["MiniMax:default"]`

因此，这条验证线现在已经不只是 `clean strict-route`，而是从 `1d + 2d + 5d` 继续升级到了包含 `2026-02-02..2026-02-10` 的 `single-provider-only session` 实证链。

补充约束：

1. extended-window rerun 虽然保持了 `fallback_attempts=0` 与 `providers_seen=["MiniMax"]`，但 `llm_route_provenance` 同时记录了 `attempts=325`、`successes=142`、`errors=183`、`rate_limit_errors=23`。
2. 这说明 provider 隔离结论成立，但模型侧稳定性并不平滑；extended-window 应写成“single-provider provenance 成立且伴随明显限流/错误压力”，而不是写成“无扰动 clean run”。

## 2. 运行对象

| 项目 | 值 |
| --- | --- |
| Probe A Report Dir | `data/reports/paper_trading_probe_20260202_single_provider_m2_7_20260320` |
| Probe A Window | `2026-02-02..2026-02-02` |
| Probe A LLM Metrics Summary | `logs/llm_metrics_20260320_031234.summary.json` |
| Probe B Report Dir | `data/reports/paper_trading_probe_20260202_20260203_single_provider_m2_7_rerun_20260320` |
| Probe B Window | `2026-02-02..2026-02-03` |
| Probe B LLM Metrics Summary | `logs/llm_metrics_20260320_115009.summary.json` |
| Probe C Report Dir | `data/reports/paper_trading_probe_20260202_20260206_single_provider_m2_7_rerun_20260320` |
| Probe C Window | `2026-02-02..2026-02-06` |
| Probe C LLM Metrics Summary | `logs/llm_metrics_20260320_122051.summary.json` |
| Probe D Report Dir | `data/reports/paper_trading_probe_20260202_20260210_single_provider_m2_7_rerun_20260320` |
| Probe D Window | `2026-02-02..2026-02-10` |
| Probe D Status | `completed` |
| Probe D Runtime Log | `logs/single_provider_probe_20260202_20260210_m2_7_rerun_20260320.log` |
| Probe D LLM Metrics Summary | `logs/llm_metrics_20260320_143631.summary.json` |
| Plan Mode | `live_pipeline` |
| Model Route | `MiniMax:MiniMax-M2.7` |

## 3. 核心观测

### 3.1 Provider provenance

| 字段 | 数值 |
| --- | --- |
| Probe A Attempts | `49` |
| Probe A Successes | `49` |
| Probe B Attempts | `99` |
| Probe B Successes | `99` |
| Probe C Attempts | `138` |
| Probe C Successes | `138` |
| Probe D Attempts | `325` |
| Probe D Successes | `142` |
| Errors | `0 / 0 / 0 / 183` |
| Rate Limit Errors | `0 / 0 / 0 / 23` |
| Fallback Attempts | `0 / 0 / 0 / 0` |
| Providers Seen | `MiniMax / MiniMax / MiniMax / MiniMax` |
| Models Seen | `MiniMax:MiniMax-M2.7 / MiniMax:MiniMax-M2.7 / MiniMax:MiniMax-M2.7 / MiniMax:MiniMax-M2.7` |
| Routes Seen | `MiniMax:default / MiniMax:default / MiniMax:default / MiniMax:default` |

### 3.2 窗口运行特征

| 指标 | 数值 |
| --- | --- |
| Probe A Day Count | `1` |
| Probe A Executed Trade Days | `0` |
| Probe A Total Executed Orders | `0` |
| Probe A Total Day Seconds | `560.52s` |
| Probe B Day Count | `2` |
| Probe B Executed Trade Days | `1` |
| Probe B Total Executed Orders | `2` |
| Probe B Final Value | `99982.7028` |
| Probe B Final Cash | `90100.7028` |
| Probe B Final Positions | `601600 x400`, `603993 x200` |
| Probe C Day Count | `5` |
| Probe C Executed Trade Days | `3` |
| Probe C Total Executed Orders | `5` |
| Probe C Avg Total Day Seconds | `337.46s` |
| Probe C Final Value | `97591.1459` |
| Probe C Final Cash | `85838.1459` |
| Probe C Final Positions | `601600 x400`, `603993 x300` |
| Probe D Day Count | `7` |
| Probe D Executed Trade Days | `3` |
| Probe D Total Executed Orders | `4` |
| Probe D Final Value | `99448.4515` |
| Probe D Final Cash | `74425.4515` |
| Probe D Final Positions | `601600 x400`, `603993 x300`, `300724 x100` |

### 3.3 计划面信号

1. `1d` probe 中，Layer B 最终保留 `603993`、`601899`、`300724`、`601600` 四个对象，buy order 生成了 `601600` 与 `603993`，但当日没有实际成交。
2. `2d` rerun 中，窗口到第二个交易日后实际执行了两笔买入：`601600 x400` 与 `603993 x200`。
3. `5d` rerun 中，组合在五个交易日内共经历 `3` 个成交日和 `5` 笔已执行订单，期末仍保留 `601600 x400` 与 `603993 x300` 两个真实持仓。
4. `5d` rerun 的资金曲线从 `100000.0` 依次走到 `99982.70`、`100180.71`、`97545.15`、`97591.15`，说明 provider 隔离结论是在真实状态推进和波动暴露下得到的，而不是建立在“完全无成交、完全无状态推进”的空跑基础上。
5. extended-window rerun 的资金曲线最终落在 `99448.4515`，期末仍保留三只持仓，进一步说明 session 级 provider 隔离可以在更长窗口与多日持仓延续下成立。
6. 但 extended-window 同时暴露出明显的 MiniMax 限流与错误压力，因此当前这条验证线的首要价值仍然是验证 provider 隔离，而不是评价收益优劣或稳定性。

## 4. 语义边界

这次结果回答的是：

1. 在全局 route allowlist 与 fallback 禁用同时开启时，session 级 provider 使用面是否会收敛为单 provider。
2. 回答结果是：会，且当前 `1d`、`2d` 与 `5d` 三级实测窗口都已经成立。

它没有回答的是：

1. `MiniMax-M2.7` 是否可替代当前 `MiniMax-M2.5` baseline。
2. 更长窗口下是否仍然保持同样低扰动、低错误率的稳定运行质量。
3. 策略收益、利用率、部署深度是否因此改善。

## 5. 直接影响

1. `single-provider-only session` 这条验证线现在已经从“设计方案”升级为“已完成 `1d + 2d + 5d + extended-window` 实证”。
2. 下一步若继续扩展，应从当前 extended-window 结果继续向更长窗口推进，或单独做稳定性/限流压力分析，而不是回退到仅讨论开关设计。
3. 即使继续扩窗，这条线仍应归档为 `MiniMax-M2.7` 分支验证，不进入当前 `MiniMax-M2.5` baseline 主序列。
4. 当前最值得补的不是“是否 single-provider”，而是 extended-window 下高错误率与 rate-limit 压力的解释与可控性分析。

## 6. 相关产物

1. `data/reports/paper_trading_probe_20260202_single_provider_m2_7_20260320/session_summary.json`
2. `data/reports/paper_trading_probe_20260202_single_provider_m2_7_20260320/daily_events.jsonl`
3. `data/reports/paper_trading_probe_20260202_single_provider_m2_7_20260320/pipeline_timings.jsonl`
4. `logs/single_provider_probe_20260202_m2_7_20260320.log`
5. `logs/llm_metrics_20260320_031234.summary.json`
6. `data/reports/paper_trading_probe_20260202_20260203_single_provider_m2_7_rerun_20260320/session_summary.json`
7. `data/reports/paper_trading_probe_20260202_20260203_single_provider_m2_7_rerun_20260320/daily_events.jsonl`
8. `data/reports/paper_trading_probe_20260202_20260203_single_provider_m2_7_rerun_20260320/pipeline_timings.jsonl`
9. `logs/single_provider_probe_20260202_20260203_m2_7_rerun_20260320.log`
10. `logs/llm_metrics_20260320_115009.summary.json`
11. `data/reports/paper_trading_probe_20260202_20260206_single_provider_m2_7_rerun_20260320/session_summary.json`
12. `data/reports/paper_trading_probe_20260202_20260206_single_provider_m2_7_rerun_20260320/daily_events.jsonl`
13. `data/reports/paper_trading_probe_20260202_20260206_single_provider_m2_7_rerun_20260320/pipeline_timings.jsonl`
14. `logs/single_provider_probe_20260202_20260206_m2_7_rerun_20260320.log`
15. `logs/llm_metrics_20260320_122051.summary.json`
16. `data/reports/paper_trading_probe_20260202_20260210_single_provider_m2_7_rerun_20260320/session_summary.json`
17. `data/reports/paper_trading_probe_20260202_20260210_single_provider_m2_7_rerun_20260320/daily_events.jsonl`
18. `data/reports/paper_trading_probe_20260202_20260210_single_provider_m2_7_rerun_20260320/pipeline_timings.jsonl`
19. `logs/single_provider_probe_20260202_20260210_m2_7_rerun_20260320.log`
20. `logs/llm_metrics_20260320_143631.summary.json`
