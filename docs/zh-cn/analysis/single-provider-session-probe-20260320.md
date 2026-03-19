# Single-Provider Session Probe

## 1. 结论

`2026-02-02` 单日 short-window probe 已经完成，当前仓库新增的 session 级 provider 闸门在最小实测窗口下成立。

本次运行同时设置：

1. `LLM_DEFAULT_MODEL_PROVIDER=MiniMax`
2. `LLM_DEFAULT_MODEL_NAME=MiniMax-M2.7`
3. `MINIMAX_MODEL=MiniMax-M2.7`
4. `LLM_DISABLE_FALLBACK=true`
5. `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax`

最终 `session_summary.json.llm_route_provenance` 显示：

1. `fallback_attempts=0`
2. `contaminated_by_provider_fallback=false`
3. `providers_seen=["MiniMax"]`
4. `models_seen=["MiniMax:MiniMax-M2.7"]`
5. `routes_seen=["MiniMax:default"]`

因此，这次 probe 已经不只是 `clean strict-route`，而是一次最小窗口下的 `single-provider-only session` 实证。

## 2. 运行对象

| 项目 | 值 |
| --- | --- |
| Report Dir | `data/reports/paper_trading_probe_20260202_single_provider_m2_7_20260320` |
| Window | `2026-02-02..2026-02-02` |
| Plan Mode | `live_pipeline` |
| Model Route | `MiniMax:MiniMax-M2.7` |
| LLM Metrics Summary | `logs/llm_metrics_20260320_031234.summary.json` |

## 3. 核心观测

### 3.1 Provider provenance

| 字段 | 数值 |
| --- | --- |
| Attempts | `49` |
| Successes | `49` |
| Errors | `0` |
| Rate Limit Errors | `0` |
| Fallback Attempts | `0` |
| Providers Seen | `MiniMax` |
| Models Seen | `MiniMax:MiniMax-M2.7` |
| Routes Seen | `MiniMax:default` |

### 3.2 当日运行特征

| 指标 | 数值 |
| --- | --- |
| Day Count | `1` |
| Executed Trade Days | `0` |
| Total Executed Orders | `0` |
| Total Day Seconds | `560.52s` |
| Post Market Seconds | `559.364s` |
| Fast Agent Seconds | `535.448s` |
| Layer-B Count | `4` |
| Watchlist Count | `3` |
| Buy Order Count | `2` |

### 3.3 计划面信号

1. 当日 Layer B 最终保留 `603993`、`601899`、`300724`、`601600` 四个对象。
2. watchlist 保留 `603993`、`300724`、`601600` 三个对象。
3. buy order 生成了 `601600` 与 `603993` 两个候选，但当日没有实际成交，最终组合仍为空仓。
4. 这说明本次 probe 的价值主要是验证 provider 隔离，而不是评估收益质量。

## 4. 语义边界

这次结果回答的是：

1. 在全局 route allowlist 与 fallback 禁用同时开启时，session 级 provider 使用面是否会收敛为单 provider。
2. 回答结果是：会，且当前最小实测窗口已经成立。

它没有回答的是：

1. `MiniMax-M2.7` 是否可替代当前 `MiniMax-M2.5` baseline。
2. 更长窗口下是否仍然保持相同隔离结果。
3. 策略收益、利用率、部署深度是否因此改善。

## 5. 直接影响

1. `single-provider-only session` 这条验证线现在已经从“设计方案”升级为“已完成最小实证”。
2. 之后若要继续扩展这条线，应从 `1d` 升到 `2d/5d`，而不是回退到仅讨论开关设计。
3. 即使继续扩窗，这条线仍应归档为 `MiniMax-M2.7` 分支验证，不进入当前 `MiniMax-M2.5` baseline 主序列。

## 6. 相关产物

1. `data/reports/paper_trading_probe_20260202_single_provider_m2_7_20260320/session_summary.json`
2. `data/reports/paper_trading_probe_20260202_single_provider_m2_7_20260320/daily_events.jsonl`
3. `data/reports/paper_trading_probe_20260202_single_provider_m2_7_20260320/pipeline_timings.jsonl`
4. `logs/single_provider_probe_20260202_m2_7_20260320.log`
5. `logs/llm_metrics_20260320_031234.summary.json`
