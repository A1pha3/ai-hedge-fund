# Single-provider / ARK / Volcengine 并发场景矩阵

**文档日期**：2026 年 3 月 20 日  
**目的**：回答三个问题：

1. 什么情况下系统仍然是 single-provider。
2. 为什么已经配置 `ARK_API_KEY`，运行时仍然可能只有 MiniMax 在工作。
3. `VOLCENGINE_PROVIDER_CONCURRENCY_LIMIT=4` 与 `doubao-seed-2.0-pro` 什么时候会真正缓解 MiniMax 压力。

---

## 1. 先给结论

`ARK_API_KEY` 的存在，表示 **Volcengine Ark 可以成为候选 provider**，不表示它一定已经进入本次 run 的有效并发波次。

系统是否 single-provider，取决于 **最终可用 route 集合**，不是取决于 `.env` 里是否出现了某个 key。

最终判定链路是：

1. provider 是否在 registry 中注册。
2. 对应 key 是否可用。
3. 是否被 `LLM_PROVIDER_ROUTE_ALLOWLIST` 从全局 route 层裁掉。
4. 是否被 `LLM_PARALLEL_PROVIDER_ALLOWLIST` 从 analyst parallel wave 层裁掉。
5. 经过以上过滤后，parallel provider 数量是否仍然大于等于 2。

只有最后剩下至少 2 个 provider，`build_parallel_provider_execution_plan()` 才会进入真正的多 provider 并发分配。

---

## 2. 代码层判定口径

相关代码路径：

1. `src/llm/models.py:get_provider_routes()`
   - 先读取 provider registry。
   - 再应用 `LLM_PROVIDER_ROUTE_ALLOWLIST`。

2. `src/utils/llm.py:_get_available_provider_keys()`
   - 只取 `enabled_only_for="parallel"` 的 route。
   - 再应用 `LLM_PARALLEL_PROVIDER_ALLOWLIST`。

3. `src/utils/llm.py:build_parallel_provider_execution_plan()`
   - 如果过滤后活跃 provider 少于 2 个，直接退化为 single-provider plan。
   - 这时 `parallel_provider_count=1`，`effective_concurrency_limit` 也只会取该 provider 的软上限。

这就是为什么“配置了 ARK”与“本次 run 一定是双 provider 并发”之间，不能画等号。

---

## 3. 你的当前环境应该怎么理解

从当前仓库配置可以确认的前提是：

1. `MINIMAX_PROVIDER_CONCURRENCY_LIMIT=5`
2. `VOLCENGINE_PROVIDER_CONCURRENCY_LIMIT=4`
3. 已配置 `ARK_API_KEY`
4. `ARK_MODEL=doubao-seed-2.0-pro`
5. 同时还存在 Zhipu 相关 key

这说明：

1. **从“凭证存在”角度看**，Volcengine 具备进入 provider route 的条件。
2. **从“并发能力”角度看**，Volcengine 具备成为 analyst parallel wave 第二条 lane 的条件。
3. 但 **是否真的参与本次 run**，仍然要看 allowlist 与运行模式。

---

## 4. 场景矩阵

| 场景 | 关键条件 | 是否 single-provider | Volcengine 是否分担 MiniMax 并发 | 说明 |
|---|---|---:|---:|---|
| A. 默认双 provider 并行 | `ARK_API_KEY` 有效，未设置排除 Volcengine 的 allowlist | 否 | 是 | 这是你期待的“MiniMax=5 + Volcengine=4” analyst wave。总 wave size 会按 provider 软上限叠加。 |
| B. 全局 strict-route MiniMax-only | `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax` | 是 | 否 | 这是最强隔离。Volcengine 从 route registry 结果里直接消失，parallel 与 fallback 都看不到它。 |
| C. 仅 analyst wave 排除 Volcengine | `LLM_PARALLEL_PROVIDER_ALLOWLIST` 不包含 Volcengine | 对 analyst parallel plan 来说是 | 否 | 这时 parallel scheduling 只剩 MiniMax；但 priority fallback 路径仍可能看到 Volcengine。 |
| D. 禁止 fallback 但未裁 route | `LLM_DISABLE_FALLBACK=true`，且未排除 Volcengine | 不一定 | 取决于 parallel allowlist | 该开关只阻止运行时跨 provider fallback，不会自动把 parallel wave 变成 single-provider。 |
| E. ARK key 无效或缺失 | `ARK_API_KEY` 不可用 | 是或退化到其它 provider 组合 | 否 | 这时 Volcengine route 不成立，系统只会在剩余 provider 中构建 plan。 |
| F. base run 不是通过 parallel execution plan 进入 | 没有注入 `agent_llm_overrides` 的旧调用路径 | 可能表现为单主 provider + fallback | 否，除非命中 fallback | 这种路径不是 analyst lane 并发分配，而是 `call_llm()` 的主 provider + fallback 语义。 |

---

## 5. 最常见的“为什么会 single-provider”

### 5.1 `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax`

这是最直接的一种。

一旦设置：

1. `get_provider_routes()` 只会返回 MiniMax route。
2. Volcengine 虽然有 key，也不会出现在 route 候选集里。
3. `build_parallel_provider_execution_plan()` 看到的 active provider 数量就是 1。

这正是本轮 `single-provider session` 验证分支采用的口径。

### 5.2 `LLM_PARALLEL_PROVIDER_ALLOWLIST` 把 Volcengine 排除了

这是一种“局部 single-provider”。

表现为：

1. analyst parallel wave 里只剩 MiniMax。
2. 但运行时如果没有 `LLM_DISABLE_FALLBACK=true`，某些单次 LLM 调用仍可能 fallback 到 Volcengine。

所以它不是“全局 MiniMax-only”，而是“analyst 并发分配层只有 MiniMax”。

### 5.3 当前代码路径根本没有进入 parallel planner

如果某条调用路径没有通过 `build_parallel_provider_execution_plan()` 注入 `metadata.agent_llm_overrides`，那它不会自动做 provider lane 分流。

这种情况下更接近：

1. 先用当前主 provider。
2. 只有在 rate limit / quota 错误时，才沿 fallback chain 切到下一 provider。

也就是说，Volcengine 只是在“兜底”，不是在“同时分担”。

---

## 6. `LLM_DISABLE_FALLBACK=true` 到底会不会造成 single-provider

会不会，要分两层看：

1. **对 parallel planner**
   - 不会直接造成 single-provider。
   - 它不改变 provider 是否进入 analyst 并发波次。

2. **对单次调用失败后的运行时行为**
   - 会阻止 `MiniMax -> Volcengine` 的自动切换。
   - 因此一旦 MiniMax 遇到 429 或连接异常，系统会 fail-closed，而不是把错误压力转移给 Ark。

所以：

1. `LLM_DISABLE_FALLBACK=true` 不是“路由裁剪器”。
2. `LLM_PROVIDER_ROUTE_ALLOWLIST` 才是“全局路由裁剪器”。

---

## 7. `VOLCENGINE_PROVIDER_CONCURRENCY_LIMIT=4` 什么时候真的有收益

只有在以下条件同时满足时，Volcengine 才能真正缓解 MiniMax 压力：

1. Volcengine route 存在。
2. Volcengine 没被 `LLM_PROVIDER_ROUTE_ALLOWLIST` 裁掉。
3. Volcengine 没被 `LLM_PARALLEL_PROVIDER_ALLOWLIST` 排除出 analyst parallel wave。
4. 当前执行路径调用了 `build_parallel_provider_execution_plan()`。

一旦以上条件满足，`MiniMax=5 + Volcengine=4` 的含义就是：

1. 同一轮 analyst wave 最多可以放 9 个 lane。
2. MiniMax 最多承担 5 个 lane。
3. Volcengine 最多承担 4 个 lane。
4. 这会降低 MiniMax 独自承压时的 burst 密度。

但它降低的是 **并发分流压力**，不是保证所有 run 都更快，也不是保证质量一定更稳。

如果 Volcengine 单次响应明显更慢，或者某窗口下 workflow/barrier 放大了慢 lane 的等待成本，总 wall-clock 仍可能回退。这也是为什么历史验证里“更高并发上限”与“更优总运行时”并不总是同义。

---

## 8. 对你当前问题的直接回答

### 8.1 什么场景会有 single-provider

最核心的几类：

1. 设置了 `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax`。
2. `LLM_PARALLEL_PROVIDER_ALLOWLIST` 把 Volcengine 排除了，导致 analyst wave 只剩 MiniMax。
3. ARK key 虽然存在，但 Volcengine route 因配置无效而没有成功注册为可用 route。
4. 当前调用路径没有进入 parallel planner，只是单 provider 主路由加 fallback。

### 8.2 我已经配置了 `ARK_API_KEY`，为什么仍可能 single-provider

因为 `ARK_API_KEY` 只解决“Volcengine 有资格被选中”，并不解决“它一定进入本次有效 route 集合”。

真正决定权在：

1. 全局 route allowlist。
2. parallel provider allowlist。
3. 当前执行路径是否使用 parallel execution plan。

### 8.3 `VOLCENGINE_PROVIDER_CONCURRENCY_LIMIT=4` + `doubao-seed-2.0-pro` 能不能缓解 MiniMax 压力

能，但前提是 Volcengine 真正进入 parallel wave。

如果它只是 fallback provider，那么它缓解的是“MiniMax 出错后的兜底可用性”，不是“正常路径的并发压力”。

---

## 9. 本轮建议

如果你的目标是：

1. 平时让 Volcengine 分担 MiniMax analyst 压力。
2. 但在做 clean validation 时仍能得到可审计的 MiniMax-only artifact。

那么建议把两种模式明确分开：

### 模式 A：日常吞吐模式

1. 不设置 `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax`
2. `LLM_PARALLEL_PROVIDER_ALLOWLIST=MiniMax,Volcengine`
3. 保留 `MINIMAX_PROVIDER_CONCURRENCY_LIMIT=5`
4. 保留 `VOLCENGINE_PROVIDER_CONCURRENCY_LIMIT=4`

### 模式 B：strict-route 验证模式

1. `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax`
2. `LLM_DISABLE_FALLBACK=true`

这样不会再把“为了验证 provenance 的 single-provider run”与“为了吞吐减压的双 provider run”混成一件事。