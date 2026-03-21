# LLM 路由与压力观测使用说明

**文档日期**：2026 年 3 月 21 日  
**用途**：说明如何使用当前仓库新增的 execution plan provenance 与 LLM observability 字段，判断：

1. 某次 run 是否真的是 single-provider。
2. `MiniMax=5 + Volcengine=4` 是否在正常路径里真实分担了压力。
3. 哪一天、哪个 tier、哪个 provider 出现了 rate limit、fallback 或慢调用。

---

## 1. 先看三层产物

当前仓库已经把同一类信息落在三层：

1. **运行时日志**
   - 入口：`run_hedge_fund()` 启动时输出 `LLM execution plan`。
   - 适合看“本次 planner 打算怎么分流”。

2. **单日事件**
   - 文件：`daily_events.jsonl`
   - 文件：`pipeline_timings.jsonl`
   - 适合看“某一天实际上是怎么跑的”。

3. **最终汇总**
   - 文件：`session_summary.json`
   - 适合看“整个窗口的 provider 路由证据”和“按 trade_date / tier / provider 的压力摘要”。

建议阅读顺序：

1. 先看 `session_summary.json`
2. 再定位到具体日期的 `daily_events.jsonl` / `pipeline_timings.jsonl`
3. 最后需要时再回看原始 `llm_metrics_*.jsonl`

如果你只是刚改完 `.env`，还没开始跑窗口，先不要直接看产物；先用下面这条命令做静态路由检查：

```bash
.venv/bin/python scripts/inspect_llm_routing.py --agent-count 8 --per-provider-limit 2
```

这条脚本会直接打印：

1. 当前默认模型
2. 当前环境下可见的 `parallel` routes
3. 当前环境下可见的 `priority` routes
4. 当前 execution plan 的 provenance 摘要
5. 一个 sample agent assignment 预览

如果这里已经看不到 `Volcengine`，那就不需要再跑长窗口去验证了，说明 `.env` 还没配对。

---

## 2. 最关键的两个字段

### 2.1 `execution_plan_provenance`

它回答的是：

1. planner 看到哪些 active providers。
2. 当前是 `single-provider` 还是 `parallel`。
3. 每个 provider 的 lane cap 是多少。
4. allowlist 有没有把某个 provider 裁掉。

重点字段：

1. `planning_mode`
2. `active_provider_names`
3. `provider_lane_limits`
4. `effective_concurrency_limit`
5. `llm_provider_route_allowlist`
6. `llm_parallel_provider_allowlist`
7. `single_provider_reason`

### 2.2 `llm_observability_summary`

它回答的是：

1. 哪个 provider 实际产生了调用。
2. 调用集中在哪个 `trade_date`。
3. 调用集中在 `fast` 还是 `precise`。
4. 哪些上下文出现了 `rate_limit_errors` 或 `fallback_attempts`。

重点字段：

1. `by_trade_date`
2. `by_model_tier`
3. `by_provider`
4. `context_breakdown`

其中 `context_breakdown` 最有用，因为它把下面 4 个维度合并起来：

1. `trade_date`
2. `pipeline_stage`
3. `model_tier`
4. `provider`

---

## 3. 如何判断“这次是不是 single-provider”

先看 `session_summary.json` 里的 `execution_plan_provenance`。

### 判定规则

如果出现下面任意一种情况，就说明这次 run 在 planner 层已经收束成 single-provider：

1. `planning_mode == "single-provider"`
2. `active_provider_names` 只有 1 个
3. `parallel_provider_count == 1`
4. `single_provider_reason` 有值

### 最常见原因

1. `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax`
2. `LLM_PARALLEL_PROVIDER_ALLOWLIST` 没有包含 Volcengine
3. Volcengine route 没成功进入可用 provider 集合

### 不要误判的点

仅仅看到 `ARK_API_KEY` 已配置，不能推出这次 run 一定是双 provider。

真正决定权在最终 execution plan，而不是原始 `.env`。

---

## 4. 如何判断“Volcengine=4 有没有真实分担 MiniMax 压力”

这个问题不能只看一层，要看两层。

### 第一步：看 planner 有没有真的让 Volcengine 进入并发波次

看 `execution_plan_provenance`：

1. `planning_mode == "parallel"`
2. `active_provider_names` 同时包含 `MiniMax` 和 `Volcengine Ark`
3. `provider_lane_limits` 类似：
   - `MiniMax: 5`
   - `Volcengine Ark: 4`

如果这里不成立，那么 Volcengine 根本没有进入 analyst parallel wave，后面的“分担压力”就无从谈起。

### 第二步：看 metrics 里是否真的出现了 Volcengine 调用

再看 `llm_observability_summary`：

1. `by_provider` 里是否存在 `Volcengine`
2. `context_breakdown` 里是否存在：
   - `provider = Volcengine`
   - `model_tier = fast` 或 `precise`
   - 对应 `trade_date`

只有两步都成立，才能说：

> Volcengine 不只是被 planner 选中了，而且在实际运行里也真的承担了部分请求。

---

## 5. 如何判断“Volcengine 只是 fallback，还是正常路径就参与了分流”

这是非常关键的区别。

### 情况 A：正常路径参与分流

特征：

1. `execution_plan_provenance.planning_mode == "parallel"`
2. `active_provider_names` 包含 Volcengine
3. `context_breakdown` 中 Volcengine 有 attempts
4. 这些 attempts 不一定伴随 `fallback_attempts > 0`

这说明 Volcengine 是在正常并行波次里承担请求。

### 情况 B：只是 fallback provider

特征：

1. execution plan 本身没有双 provider 并发，或者 active providers 里没有 Volcengine
2. 但 `llm_route_provenance.fallback_attempts > 0`
3. 同时 `context_breakdown` 中出现 Volcengine 请求

这说明 Volcengine 的作用更接近：

1. MiniMax 出错后的兜底
2. 而不是正常路径的吞吐分流

注意：

1. `execution_plan_provenance.provider_routes` 里展示的 `display_name` 仍可能是 `Volcengine Ark`。
2. 但 metrics / summary 里的 provider 归类键使用的是 `provider_name`，也就是 `Volcengine`。
3. 排查时要按字段语义看，不要把 display name 和 provider key 混用。

---

## 6. 如何定位“哪一天 MiniMax 压力最大”

优先看 `llm_observability_summary.by_trade_date`。

你应该先比较：

1. `attempts`
2. `rate_limit_errors`
3. `fallback_attempts`
4. `avg_duration_ms`

如果某一天的 `attempts` 高、`rate_limit_errors` 高、`fallback_attempts` 也高，那么这一天就是高风险日。

然后去 `context_breakdown` 里定位：

1. 是 `fast` 还是 `precise`
2. 是 `MiniMax` 还是 `Volcengine Ark`
3. 是否集中在 `daily_pipeline_post_market`

最后再回到同一天的：

1. `daily_events.jsonl`
2. `pipeline_timings.jsonl`

确认当天的 execution plan 是否已经是双 provider，还是已经退化成 single-provider。

---

## 7. 如何判断“fast tier 才是主要压力源”

看 `llm_observability_summary.by_model_tier`。

如果：

1. `fast.attempts` 远高于 `precise.attempts`
2. `fast.rate_limit_errors` 也显著更高
3. `fast` 下 MiniMax 的 `avg_duration_ms` 或 `fallback_attempts` 更突出

就可以 reasonably 判断：

> 当前窗口的主要 API 压力来自 fast tier，而不是 precise tier。

再用 `context_breakdown` 定位到具体日期即可。

---

## 8. 建议的排查顺序

如果你的问题是：

### 8.1 “这次为什么还是 MiniMax-only？”

按这个顺序看：

1. `session_summary.json.execution_plan_provenance`
2. 看 `planning_mode`
3. 看 `active_provider_names`
4. 看 `llm_provider_route_allowlist`
5. 看 `llm_parallel_provider_allowlist`
6. 看 `single_provider_reason`

### 8.2 “Volcengine=4 到底有没有缓解 MiniMax 压力？”

按这个顺序看：

1. `execution_plan_provenance.provider_lane_limits`
2. `llm_observability_summary.by_provider`
3. `llm_observability_summary.context_breakdown`
4. 同一天的 `pipeline_timings.jsonl`

### 8.3 “哪一天最值得深挖？”

按这个顺序看：

1. `llm_observability_summary.by_trade_date`
2. 找 `rate_limit_errors` 最高的日期
3. 进入 `context_breakdown` 看 provider + tier
4. 再看该日 `daily_events.jsonl` 和 `pipeline_timings.jsonl`

---

## 9. 你当前配置下的推荐读法

如果你当前目标是验证：

1. 平时用 `MiniMax=5 + Volcengine=4` 分流
2. 验证时切到 strict-route MiniMax-only

那么建议这样解读产物：

### 日常吞吐模式

你希望看到：

1. `execution_plan_provenance.planning_mode == "parallel"`
2. `provider_lane_limits` 里同时有 `MiniMax` 和 `Volcengine Ark`
3. `llm_observability_summary.by_provider` 里两者都有 attempts

### strict-route 验证模式

你希望看到：

1. `planning_mode == "single-provider"`
2. `active_provider_names == ["MiniMax"]`
3. `llm_route_provenance.providers_seen == ["MiniMax"]`
4. 没有 Volcengine attempts

---

## 10. 一句话口径

你以后可以用下面这条口径快速判断：

1. **execution plan provenance** 负责回答“系统本来打算怎么分流”。
2. **LLM observability summary** 负责回答“系统实际上是谁在承压”。
3. **daily events / timing logs** 负责回答“哪一天发生了什么”。

三层都对齐时，才算真正证明：

> `MiniMax=5 + Volcengine=4` 不只是配置存在，而是已经在实际窗口里真实分担了压力。
