# Single-Provider Extended-Window Stability Analysis

## 1. 结论

`2026-02-02..2026-02-10` 这档 MiniMax-only extended-window rerun 已经完成两件彼此独立的验证：

1. provider provenance 通过，`fallback_attempts=0`、`providers_seen=["MiniMax"]`、`routes_seen=["MiniMax:default"]`，说明这次运行确实是 fail-closed 的单 provider session。
2. 运行稳定性不通过 clean-run 口径，`attempts=325` 中仅 `142` 次成功，`183` 次失败，且失败主因不是单纯 `429`，而是以 `APIConnectionError` 为主的连接不稳定。

因此，这次 extended-window 的正确描述应是：

1. single-provider provenance 成立。
2. MiniMax 侧存在明显稳定性压力。
3. 该结果可以作为 provider 隔离分支的验收证据，但不能作为“运行质量平滑”或“可直接替代 baseline”的证据。

## 2. 核心指标

| 指标 | 数值 |
| --- | --- |
| Attempts | `325` |
| Successes | `142` |
| Errors | `183` |
| Success Rate | `43.7%` |
| Error Rate | `56.3%` |
| Rate Limit Errors | `23` |
| Fallback Attempts | `0` |
| Providers Seen | `MiniMax` |
| Models Seen | `MiniMax:MiniMax-M2.7` |
| Routes Seen | `MiniMax:default` |

按错误类型拆解：

| Error Type | Count | 占总尝试比例 | 占失败比例 |
| --- | --- | --- | --- |
| `APIConnectionError` | `159` | `48.9%` | `86.9%` |
| `RateLimitError` | `23` | `7.1%` | `12.6%` |
| `ValidationError` | `1` | `0.3%` | `0.5%` |

这组数据已经足够说明：extended-window 的主要矛盾不是 schema 输出质量，也不是纯粹的 quota 命中，而是连接稳定性先出问题，429 作为次级压力叠加出现。

## 3. 失败形态

### 3.1 连接错误是第一主因

原始 LLM metrics jsonl 中，大量失败记录表现为：

1. `error_type="APIConnectionError"`
2. `error_message="Connection error."`
3. 错误在多个 agent 上分布，而不是集中在单一 prompt 或单一 schema

这说明 extended-window 内的失败更像 MiniMax 侧 transport / connection 抖动，而不是本地某个 analyst prompt 全面失效。

### 3.2 429 压力是真实存在的，但不是全部解释

runtime log 中可以看到多次：

1. `Retrying request to /chat/completions`
2. `HTTP/1.1 429 Too Many Requests`
3. provider 明确提示“当前处于高峰时段，Token Plan 的速率限制可能会临时收紧。请稍后重试，并请适当控制请求并发度。”

这说明 rate-limit 压力并非推测，而是 provider 明确返回的运行时信号。但从总量上看，`429` 只占 `23/183` 个失败，不能把 extended-window 的全部问题简化成“只是高峰期限流”。

### 3.3 schema 问题是边缘噪声，不是主线原因

这次窗口只看到 `1` 个 `ValidationError`，发生在 `PeterLynchSignal.reasoning_cn`。这类错误需要记录，但不会改变这次窗口的主判断，因为它既不解释大多数失败，也不解释大多数 runtime 放大。

## 4. 受影响范围

失败分布跨越多名 investor agent、分析 agent 与 manager，不支持“某一位 agent 特别坏”这种单点归因。已确认的代表性失败对象包括：

1. `bill_ackman_agent`
2. `cathie_wood_agent`
3. `charlie_munger_agent`
4. `michael_burry_agent`
5. `mohnish_pabrai_agent`
6. `peter_lynch_agent`
7. `phil_fisher_agent`
8. `rakesh_jhunjhunwala_agent`
9. `warren_buffett_agent`
10. `stanley_druckenmiller_agent`
11. `news_sentiment_agent`
12. `portfolio_manager`

其中 `cathie_wood_agent` 的 rate-limit 命中尤其明显，说明压力在 investor cohort 内有聚集，但整体仍呈现“多 agent 同时受影响”的系统性特征。

## 5. 运行时放大位置

pipeline timing 显示耗时主要堆积在 `post_market` 内的 `fast_agent`，而不是别的阶段。代表性日期如下：

| Trade Date | Fast Agent | Post Market | Total Day | Precise Stage |
| --- | --- | --- | --- | --- |
| `20260202` | `908.017s` | `930.084s` | `931.260s` | `skipped=true` |
| `20260209` | `583.288s` | `599.141s` | `600.778s` | `skipped=true` |
| `20260210` | `378.652s` | `393.992s` | `395.734s` | `skipped=true` |

这有两个直接含义：

1. runtime 放大主要发生在 fast-agent 批处理中。
2. 至少在这些最长耗时日，`precise_stage_skipped=true`，因此当前压力不能归因到 precise stage 额外负载。

换句话说，即便已经跳过 precise 阶段，MiniMax-only extended-window 仍然会因为 fast-agent 请求面上的连接抖动和 429 重试把单日耗时推高到 `6-15` 分钟量级。

## 6. 语义解释

这次窗口必须和此前的 clean strict-route 结果分开表述：

1. clean strict-route 证明默认路由没有 provider fallback contamination。
2. single-provider extended-window 进一步证明 whole-session provider surface 也被收紧到单 provider。
3. 但 extended-window 同时证明，在 `LLM_DISABLE_FALLBACK=true` 与 `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax` 下，系统会把 MiniMax 的稳定性问题完整暴露出来，而不是通过 Ark fallback 吞掉它。

因此，这次失败应该解释为：

1. 为了 auditability，系统选择 fail-closed。
2. fail-closed 成功保住了 provenance 纯度。
3. 代价是 provider-side 抖动会直接转化为 error count 与 runtime inflation。

## 7. 对当前分支的影响

这份结果已经足够支持以下判断：

1. `single-provider-only session` 分支的验证目标已经完成，不需要再重复证明“是不是只有 MiniMax”。
2. 当前分支下一步应该转向稳定性可控性，而不是继续堆叠重复 provenance artifact。
3. 在 W3 仍被 `data_not_ready` 阻塞时，这份文档就是 extended-window 阶段最需要补齐的解释性产物。

## 8. 建议的后续动作

若后续仍要继续跑 single-provider extended window，应优先做以下三类动作，而不是直接再开一轮同口径长跑：

1. 降低 fast-agent 侧有效并发或批次密度，验证 429 与 connection burst 是否随之下降。
2. 在非高峰时段重放一档同规模窗口，区分“provider 峰值时段问题”和“全天候连接不稳问题”。
3. 把 request-level retry / connection / 429 统计继续前置到 pipeline 观察面，避免只在 run 结束后从日志回溯。

## 9. 相关产物

1. `data/reports/paper_trading_probe_20260202_20260210_single_provider_m2_7_rerun_20260320/session_summary.json`
2. `data/reports/paper_trading_probe_20260202_20260210_single_provider_m2_7_rerun_20260320/pipeline_timings.jsonl`
3. `logs/llm_metrics_20260320_143631.summary.json`
4. `logs/llm_metrics_20260320_143631.jsonl`
5. `logs/single_provider_probe_20260202_20260210_m2_7_rerun_20260320.log`
6. [single-provider-session-probe-20260320.md](./single-provider-session-probe-20260320.md)
7. [llm-routing-and-minimax-config-20260319.md](./llm-routing-and-minimax-config-20260319.md)
