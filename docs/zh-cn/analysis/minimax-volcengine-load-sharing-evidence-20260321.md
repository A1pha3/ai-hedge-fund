# MiniMax 与 Volcengine 分流实证纪要

**文档日期**：2026 年 3 月 21 日  
**目的**：把“当前 `.env` 是否已经启用 MiniMax + Volcengine 并行”与“Volcengine 是否真的分担了 MiniMax 压力”拆成两层证据来确认。

---

## 1. 当前 `.env` 的静态路由结论

使用命令：

```bash
.venv/bin/python scripts/inspect_llm_routing.py --agent-count 12 --per-provider-limit 2
```

当前环境下的 planner 预览结果是：

1. `planning_mode = parallel`
2. `active_provider_names = ["MiniMax", "Volcengine"]`
3. `provider_lane_limits = {"MiniMax": 5, "Volcengine": 4}`
4. `effective_concurrency_limit = 9`
5. `llm_parallel_provider_allowlist = ["MiniMax", "Volcengine"]`
6. `llm_provider_route_allowlist = null`

这说明当前配置已经满足下面这件事：

> analyst 并行波次会按 `MiniMax=5 + Volcengine=4` 做正常分流，而不是 MiniMax-only。

同时也要注意：

1. 当前只限制了 analyst parallel wave。
2. 全局 route allowlist 仍然没有打开。
3. 因此某些非并行主路径或 priority 路径，理论上仍可能看到 Zhipu route 可见。

换句话说，当前 `.env` 是“吞吐优先的双 provider 并行模式”，不是“全局严格双 provider-only 模式”。

---

## 2. 真实窗口对照：single-provider 与 dual-provider

下面选了四个真实 summary 文件做对照：

1. `logs/llm_metrics_20260320_122051.summary.json`：MiniMax-only 稳定窗口
2. `logs/llm_metrics_20260320_143631.summary.json`：MiniMax-only 失稳窗口
3. `logs/llm_metrics_ab_dual_provider_validation_20260311_5d_tuned_dedup_mx5_doubao4_allowlist_true.summary.json`：5 日双 provider allowlist 窗口
4. `logs/llm_metrics_ab_dual_provider_validation_20260312_20d_best_mx5_doubao4_allowlist.summary.json`：20 日双 provider allowlist 窗口

### 2.1 汇总对比

| 窗口 | Attempts | 成功率 | 错误率 | Rate Limit 占比 | 平均耗时 |
|------|----------|--------|--------|------------------|----------|
| MiniMax-only 稳定窗口 | 138 | 100.00% | 0.00% | 0.00% | 20465 ms |
| MiniMax-only 失稳窗口 | 325 | 43.69% | 56.31% | 7.08% | 13801 ms |
| 5 日双 provider allowlist | 129 | 98.45% | 1.55% | 0.00% | 22524 ms |
| 20 日双 provider allowlist | 402 | 97.01% | 2.99% | 0.00% | 19032 ms |

这个表先说明一件核心事实：

> single-provider 不一定一定失败，但一旦 MiniMax-only 压力失稳，错误率会直接放大；而双 provider 窗口整体成功率保持在 97% 到 98% 以上，且没有出现 rate limit 错误。

---

## 3. Volcengine 是否真的承担了请求

### 3.1 5 日双 provider allowlist 窗口

文件：`logs/llm_metrics_ab_dual_provider_validation_20260311_5d_tuned_dedup_mx5_doubao4_allowlist_true.summary.json`

| Provider | Attempts | 占比 | 平均耗时 | 错误率 |
|----------|----------|------|----------|--------|
| MiniMax | 72 | 55.81% | 23088 ms | 2.78% |
| Volcengine | 50 | 38.76% | 18793 ms | 0.00% |
| Zhipu | 7 | 5.43% | 43364 ms | 0.00% |

结论：

1. Volcengine 并不是“几乎没参与”，而是承担了接近 39% 的调用。
2. Volcengine 平均耗时比 MiniMax 低约 4295 ms。
3. Volcengine 在该窗口没有出现错误。

### 3.2 20 日双 provider allowlist 窗口

文件：`logs/llm_metrics_ab_dual_provider_validation_20260312_20d_best_mx5_doubao4_allowlist.summary.json`

| Provider | Attempts | 占比 | 平均耗时 | 错误率 |
|----------|----------|------|----------|--------|
| MiniMax | 228 | 56.72% | 20944 ms | 4.39% |
| Volcengine | 158 | 39.30% | 15487 ms | 1.27% |
| Zhipu | 16 | 3.98% | 26777 ms | 0.00% |

结论：

1. 更长窗口里，Volcengine 仍然稳定承担约 39% 的请求。
2. Volcengine 平均耗时比 MiniMax 低约 5457 ms。
3. Volcengine 错误率也低于 MiniMax。

这已经足够证明：

> Volcengine 在历史双 provider 窗口里承担的是正常路径分流，不只是偶发 fallback。

---

## 4. 当前结论应该怎么读

### 4.1 可以确认的部分

1. 当前 `.env` 已经把 analyst 并行执行计划切到 `MiniMax + Volcengine`。
2. 历史真实窗口证明 Volcengine 能稳定承担约 39% 的调用量。
3. 在已记录窗口里，Volcengine 平均时延通常低于 MiniMax。
4. 双 provider 窗口整体成功率明显高于 MiniMax-only 失稳窗口。

### 4.2 还不能过度外推的部分

1. 历史实证窗口主要是 `MiniMax-M2.5 + doubao-seed-2.0-code`。
2. 当前静态路由预览已经切到 `MiniMax-M2.7 + doubao-seed-2.0-pro`。
3. 因此我们已经能确认“路由机制成立”，但还没有拿到一份 `M2.7 + doubao-seed-2.0-pro` 的长窗口实测 summary 来证明它在你当前配置下的最终表现曲线。

也就是说，当前已经完成了：

1. 机制层确认
2. 历史实证层确认

但还差最后一层：

3. 当前生产配置对应窗口的实跑证据

---

## 5. 对当前配置的操作建议

如果你的目标是“优先缓解 MiniMax 压力，并保持较好的吞吐与灵活性”，当前配置是合理的：

1. 保留 `LLM_PARALLEL_PROVIDER_ALLOWLIST=MiniMax,Volcengine`
2. 暂时不打开全局 `LLM_PROVIDER_ROUTE_ALLOWLIST`

如果你的目标是“无论什么路径都严格禁止 Zhipu 进入”，那就需要再加：

```bash
LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax,Volcengine
```

但这会把运行模式从“并行主波次双 provider”进一步收紧到“全局 route 也双 provider-only”，应当用一次真实窗口再验证是否有副作用。

---

## 6. 最短结论

一句话结论：

> 当前 `.env` 已经让 analyst parallel wave 进入 `MiniMax=5 + Volcengine=4` 的并行计划；历史真实窗口显示 Volcengine 稳定承接约 39% 请求，且平均耗时低于 MiniMax，因此它确实能分担 MiniMax 压力，而不是只在 fallback 时才出现。