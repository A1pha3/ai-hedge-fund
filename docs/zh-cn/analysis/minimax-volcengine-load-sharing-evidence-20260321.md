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

## 4. 当前配置的实跑证据

截至本次更新，已经补跑了三组基于当前 `.env` 的真实 artifact：

1. `data/reports/paper_trading_probe_20260202_dual_provider_m2_7_pro_summaryfix_20260321/session_summary.json`
2. `data/reports/paper_trading_probe_20260202_20260203_dual_provider_m2_7_pro_20260321/session_summary.json`
3. `data/reports/paper_trading_probe_20260202_20260206_dual_provider_m2_7_pro_20260321/session_summary.json`

对应的 provider 分流占比与平均耗时，统一以配套的 `logs/llm_metrics_*.summary.json` 为准；`session_summary.json` 主要用于确认 `execution_plan_provenance`、providers_seen 和 fallback 情况。

### 4.1 1 日 probe 结论

文件：`data/reports/paper_trading_probe_20260202_dual_provider_m2_7_pro_summaryfix_20260321/session_summary.json`

配套 metrics：`logs/llm_metrics_20260321_231636.summary.json`

关键信号：

1. `execution_plan_provenance.observation_count = 1`
2. `observations[0].execution_plan_provenance.active_provider_names = ["MiniMax", "Volcengine"]`
3. `provider_lane_limits = {"MiniMax": 5, "Volcengine": 4}`
4. `llm_metrics_20260321_231636.summary.json`：
	- `MiniMax = 29` 次，占比 `59.18%`，平均 `28488 ms`
	- `Volcengine = 20` 次，占比 `40.82%`，平均 `25196 ms`
5. `attempts = 49`，`successes = 49`，`errors = 0`，`fallback_attempts = 0`

这组 1 日 probe 的价值主要是两点：

1. 再次确认当前配置的真实双 provider 运行成立。
2. 确认修复后，`session_summary.json` 已经能正确汇总 per-day `execution_plan_provenance`，不再出现“timing log 有、summary 为空”的情况。

### 4.2 2 日 probe 结论

文件：`data/reports/paper_trading_probe_20260202_20260203_dual_provider_m2_7_pro_20260321/session_summary.json`

配套 metrics：`logs/llm_metrics_20260321_230128.summary.json`

关键信号：

1. `llm_route_provenance.providers_seen = ["MiniMax", "Volcengine"]`
2. `models_seen = ["MiniMax:MiniMax-M2.7", "Volcengine:doubao-seed-2.0-pro"]`
3. `attempts = 99`，`successes = 99`，`errors = 0`
4. `logs/llm_metrics_20260321_230128.summary.json`：
	- `MiniMax = 59` 次，占比 `59.60%`，平均 `28487 ms`
	- `Volcengine = 40` 次，占比 `40.40%`，平均 `23758 ms`
5. `fallback_attempts = 0`

这说明：

> 你当前的 `MiniMax-M2.7 + doubao-seed-2.0-pro` 配置，已经在真实 2 日窗口里以正常并行路径完成了双 provider 分流，而不是依赖 fallback 兜底。

### 4.3 5 日 probe 结论

文件：`data/reports/paper_trading_probe_20260202_20260206_dual_provider_m2_7_pro_20260321/session_summary.json`

配套 metrics：`logs/llm_metrics_20260321_233450.summary.json`

关键信号：

1. `llm_route_provenance.attempts = 138`，`successes = 138`，`errors = 0`
2. `fallback_attempts = 0`，`contaminated_by_provider_fallback = false`
3. `providers_seen = ["MiniMax", "Volcengine"]`
4. `execution_plan_provenance.observation_count = 5`
5. 五个 trade_date 的 `execution_plan_provenance` 都一致显示：
	- `planning_mode = parallel`
	- `active_provider_names = ["MiniMax", "Volcengine"]`
	- `parallel_provider_count = 2`
	- `effective_concurrency_limit = 9`
	- `single_provider_reason = null`
6. `logs/llm_metrics_20260321_233450.summary.json`：
	- `MiniMax = 83` 次，占比 `60.14%`，平均 `25538 ms`
	- `Volcengine = 55` 次，占比 `39.86%`，平均 `24265 ms`
7. 分日耗时继续保持稳定：
	- `20260202 = 49` 次，平均 `25243 ms`
	- `20260203 = 50` 次，平均 `25947 ms`
	- `20260204 = 13` 次，平均 `24680 ms`
	- `20260205 = 13` 次，平均 `23445 ms`
	- `20260206 = 13` 次，平均 `22640 ms`

这组 5 日 probe 把结论从“短窗口成立”推进到了“中窗口成立”：

> 当前 `MiniMax-M2.7 + doubao-seed-2.0-pro` 配置不只是在 1 日或 2 日里短暂成立，而是在连续 5 个交易日里持续保持双 provider 并行、0 fallback、0 错误，并且 Volcengine 继续稳定承担约 40% 的请求量。

### 4.4 严格全局 allowlist 验证

为了回答“如果进一步打开 `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax,Volcengine`，会不会把当前运行模式搞坏”，这次又补做了两层验证。

#### 静态 planner 对比

直接在同一进程里对比：

1. 当前模式：`LLM_PROVIDER_ROUTE_ALLOWLIST = null`
2. 严格模式：`LLM_PROVIDER_ROUTE_ALLOWLIST = ["MiniMax", "Volcengine"]`

结果一致：

1. `planning_mode = parallel`
2. `active_provider_names = ["MiniMax", "Volcengine"]`
3. `parallel_provider_count = 2`
4. `effective_concurrency_limit = 9`
5. `provider_lane_limits = {"MiniMax": 5, "Volcengine": 4}`
6. `single_provider_reason = null`

这说明在 planner 层面，打开全局 dual allowlist 不会把当前 analyst parallel plan 退化成 single-provider。

#### 1 日运行时对比

本次新增两组 fresh rerun：

1. 非严格模式：`data/reports/paper_trading_probe_20260202_dual_provider_m2_7_current_rerun_20260322/session_summary.json`
2. 严格模式：`data/reports/paper_trading_probe_20260202_dual_provider_m2_7_pro_strict_allowlist_venv_20260322/session_summary.json`

两者共同点：

1. `attempts = 49`，`successes = 49`，`errors = 0`
2. `providers_seen = ["MiniMax", "Volcengine"]`
3. `fallback_attempts = 0`
4. `execution_plan_provenance.observation_count = 1`
5. `active_provider_names = ["MiniMax", "Volcengine"]`
6. `single_provider_reason = null`

严格模式额外确认了：

1. `execution_plan_provenance.llm_provider_route_allowlist = ["MiniMax", "Volcengine"]`
2. 同时仍保留 `llm_parallel_provider_allowlist = ["MiniMax", "Volcengine"]`

这说明：

> 在当前 `MiniMax-M2.7 + doubao-seed-2.0-pro` 配置下，把 `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax,Volcengine` 打开后，至少在这组 1 日 fresh rerun 里没有观察到吞吐退化、single-provider 退化或 fallback 污染。

#### 10 日 strict allowlist 长窗口验证

在 1 日 strict rerun 通过后，本次继续补跑了更长窗口：

1. `data/reports/paper_trading_probe_20260202_20260213_dual_provider_m2_7_pro_strict_allowlist_venv_20260322/session_summary.json`

关键信号：

1. `attempts = 274`，`successes = 274`，`errors = 0`
2. `fallback_attempts = 0`
3. `providers_seen = ["MiniMax", "Volcengine"]`
4. provider 分流继续稳定：
	- `MiniMax = 164` 次，占比 `59.85%`，平均 `23030 ms`
	- `Volcengine = 110` 次，占比 `40.15%`，平均 `25080 ms`
5. `execution_plan_provenance.observation_count = 9`
6. 这 9 个 observation 全部满足：
	- `active_provider_names = ["MiniMax", "Volcengine"]`
	- `single_provider_reason = null`
	- `llm_provider_route_allowlist = ["MiniMax", "Volcengine"]`

这里的 `9` 不是缺数据，而是因为窗口终点 `2026-02-13` 当天：

1. `layer_b_count = 0`
2. `execution_plan_provenance = []`
3. 当日事件以持仓风控和硬止损处理为主，没有进入新的 LLM analyst 波次

因此更准确的解读是：

> 这组 strict allowlist 长窗口包含 10 个回测日，其中 9 个交易日实际触发了新的 LLM analyst 执行，而这 9 个 LLM 日全部保持双 provider、0 fallback、0 error，没有出现 single-provider 退化。

#### 10 日 strict vs current 同窗口对照

为了回答“严格全局 allowlist 是否真的改变当前运行结果”，本次又补跑了同一时间窗的非严格 current-config 基线：

1. 非严格模式：`data/reports/paper_trading_probe_20260202_20260213_dual_provider_m2_7_current_venv_20260322/session_summary.json`
2. 严格模式：`data/reports/paper_trading_probe_20260202_20260213_dual_provider_m2_7_pro_strict_allowlist_venv_20260322/session_summary.json`

同窗口对照结果：

1. 两组最终成功结果没有退化：
	- 非严格模式：`successes = 274`，`fallback_attempts = 0`
	- 严格模式：`successes = 274`，`fallback_attempts = 0`
2. 两组 `providers_seen` 完全一致，都是 `["MiniMax", "Volcengine"]`
3. 两组 `execution_plan_provenance.observation_count` 都是 `9`，且这 9 个 observation 全部满足：
	- `active_provider_names = ["MiniMax", "Volcengine"]`
	- `single_provider_reason = null`
4. 两组 provider split 也几乎重合：
	- 非严格模式：`MiniMax = 166`、`Volcengine = 110`，占比约 `60.14% / 39.86%`
	- 严格模式：`MiniMax = 164`、`Volcengine = 110`，占比约 `59.85% / 40.15%`
5. 平均耗时差异也只在正常波动范围内：
	- 非严格模式：`MiniMax = 22916 ms`，`Volcengine = 25920 ms`
	- 严格模式：`MiniMax = 23030 ms`，`Volcengine = 25080 ms`
6. 唯一可见差异是非严格模式这次多出 `2` 次 `MiniMax` 侧 `ValueError`，所以 `attempts = 276`、`errors = 2`；但这 `2` 次没有触发 provider fallback，也没有改变最终 `274/274` 的成功产出。

这组 same-window 对照的含义很直接：

> 对当前 `MiniMax-M2.7 + doubao-seed-2.0-pro` 这套配置而言，把 `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax,Volcengine` 打开，并没有带来可观察的吞吐退化、provider 退化或 single-provider 回落；至少在这个 10 日窗口里，strict 与 current 的行为是等价的。

---

## 5. 当前结论应该怎么读

### 5.1 可以确认的部分

1. 当前 `.env` 已经把 analyst 并行执行计划切到 `MiniMax + Volcengine`。
2. 历史真实窗口证明 Volcengine 能稳定承担约 39% 的调用量。
3. 在已记录窗口里，Volcengine 平均时延通常低于 MiniMax。
4. 双 provider 窗口整体成功率明显高于 MiniMax-only 失稳窗口。
5. 当前 `MiniMax-M2.7 + doubao-seed-2.0-pro` 已经在 1 日、2 日、5 日 current-config 窗口，以及 10 日 strict/current 同窗口对照里确认：
	- provider 双路可见
	- 正常并行分流成立
	- `fallback_attempts = 0`
	- strict 与 non-strict 都没有观察到 single-provider 退化
	- Volcengine 持续承担约 40% 请求

### 5.2 还不能过度外推的部分

1. 历史实证窗口主要是 `MiniMax-M2.5 + doubao-seed-2.0-code`。
2. 当前 `MiniMax-M2.7 + doubao-seed-2.0-pro` 现在已经有 10 日 same-window strict/current evidence，但仍没有 20 日这类更长窗口的最终表现曲线。
3. 因此现在已经能确认“当前生产配置在 10 日量级窗口里真实成立，且 strict route allowlist 不会明显破坏现有并行分流”，但还不能把它直接外推成“更长窗口一定同样稳定”。

也就是说，当前已经完成了：

1. 机制层确认
2. 历史实证层确认
3. 当前配置短窗口实证层确认

但还差最后一层：

4. 更长于 10 日的当前生产配置实跑证据

---

## 6. 对当前配置的操作建议

如果你的目标是“优先缓解 MiniMax 压力，并保持较好的吞吐与灵活性”，当前配置已经足够合理：

1. 保留 `LLM_PARALLEL_PROVIDER_ALLOWLIST=MiniMax,Volcengine`
2. 暂时不打开全局 `LLM_PROVIDER_ROUTE_ALLOWLIST`

如果你的目标是“无论什么路径都严格禁止 Zhipu 进入”，那就需要再加：

```bash
LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax,Volcengine
```

这会把运行模式从“并行主波次双 provider”进一步收紧到“全局 route 也双 provider-only”。

截至本次更新，已经完成了 1 日 fresh rerun 与 10 日 same-window 对照验证，结果是：

1. planner 不退化
2. 1 日 strict rerun 仍然是 `49/49` 成功
3. 10 日 strict vs current 都保持 `274` 个最终成功结果
4. `fallback_attempts = 0`
5. `providers_seen = ["MiniMax", "Volcengine"]`

所以在当前已验证范围内，如果你希望从语义上彻底排除 Zhipu，可直接打开全局 strict allowlist；它目前没有表现出明显副作用。真正还没覆盖的，只剩更长窗口表现。

---

## 7. 最短结论

一句话结论：

> 当前 `.env` 已经让 analyst parallel wave 进入 `MiniMax=5 + Volcengine=4` 的并行计划；历史真实窗口显示 Volcengine 稳定承接约 39% 请求，而当前 `MiniMax-M2.7 + doubao-seed-2.0-pro` 的 1 日、2 日、5 日真实 probe 都确认了双 provider 正常分流、`fallback_attempts = 0`、连续 5 个交易日 `single_provider_reason = null`。另外，本次新增的严格全局 allowlist 1 日 fresh rerun 也没有观察到副作用，因此这套配置已经不只是“短窗口偶然成立”，而是在中窗口与严格路由约束下都能继续分担 MiniMax 压力。
> 当前 `.env` 已经让 analyst parallel wave 进入 `MiniMax=5 + Volcengine=4` 的并行计划；历史真实窗口显示 Volcengine 稳定承接约 39% 请求，而当前 `MiniMax-M2.7 + doubao-seed-2.0-pro` 的 1 日、2 日、5 日 probe 与新增的 10 日 strict/current 同窗口对照都确认了双 provider 正常分流、`fallback_attempts = 0`、9 个 LLM observation day 持续 `single_provider_reason = null`。严格全局 allowlist 只带来了 0 成功率损失、0 fallback 增量和近乎重合的 provider split，因此如果你要从全局语义上排除 Zhipu，现在已经有足够证据支持直接打开它。