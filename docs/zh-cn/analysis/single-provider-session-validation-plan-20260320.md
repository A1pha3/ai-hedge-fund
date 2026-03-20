# Single-Provider Session Validation Plan

## 1. 目的

这份文档回答的是一个比 `clean strict-route` 更严格的问题：

1. 如何把整个 session 压成真正的 single-provider-only。
2. 它与当前 `no provider fallback contamination` 的 clean 口径有什么区别。
3. 当前仓库要做到这一点，最小需要哪些运行时控制。

## 2. 与现有 clean 口径的区别

当前已经成立的 clean 口径是：

1. 默认路由没有发生 provider fallback 污染。
2. 这主要依赖 `LLM_DISABLE_FALLBACK=true` 与 `llm_route_provenance` 的审计字段。

但它**不等于** single-provider-only session，因为：

1. analyst 并行波次仍可能通过 provider registry 把不同 agent 分发到不同 provider。
2. 只要 registry 里还有其它可用 route，session 级 `providers_seen` 就仍可能出现 `Volcengine`、`Zhipu` 等条目。

因此，single-provider-only 要比 clean 再多一道约束：

1. 不只是禁止 fallback。
2. 还要禁止其它 provider route 进入这轮 session 的初始调度面。

## 3. 当前代码下的最小可执行方案

截至 `2026-03-20`，当前仓库已经具备做 session 级单 provider 验证的最小开关组合：

```dotenv
LLM_DEFAULT_MODEL_PROVIDER=MiniMax
LLM_DEFAULT_MODEL_NAME=MiniMax-M2.7
MINIMAX_MODEL=MiniMax-M2.7
LLM_DISABLE_FALLBACK=true
LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax
```

其中：

1. `LLM_DISABLE_FALLBACK=true` 负责阻断运行中的跨 provider fallback。
2. `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax` 负责从 route registry 层直接裁掉其它 provider，使其不能进入 priority routing 和 parallel scheduling。

这两个开关合在一起，才接近真正的 single-provider-only session。

## 4. 这次新增的代码闸门做了什么

本轮新增的是全局 route allowlist：

1. 入口变量为 `LLM_PROVIDER_ROUTE_ALLOWLIST`。
2. 它作用于 `get_provider_routes()`，因此不仅影响并行波次，也影响 priority routing。
3. 当该变量设置为 `MiniMax` 时，registry 返回的可路由 provider 只剩 `MiniMax`。

这比旧的 `LLM_PARALLEL_PROVIDER_ALLOWLIST` 更严格，因为旧变量只作用于 parallel waves，不会阻止 priority routing 继续看到其它 provider。

## 5. 建议实验口径

如果后续要正式跑 single-provider session 验证，建议固定下面的文案口径：

1. `single-provider-only probe`：用于回答 session 级 provider 隔离是否成立。
2. `clean strict-route validation`：用于回答默认路由是否无 fallback 污染。
3. 两者不能混称。

推荐最小实验步骤：

1. 设置 `LLM_PROVIDER_ROUTE_ALLOWLIST=MiniMax`。
2. 设置 `LLM_DISABLE_FALLBACK=true`。
3. 先运行 `1d` short-window probe，确认 `providers_seen == ["MiniMax"]` 或等价单 provider 结果。
4. 再运行 `2d` rerun，确认单 provider 结论在真实持仓推进下仍成立。
5. 再运行 `5d` rerun，确认单 provider 结论在多日成交、持仓延续和资金曲线波动下仍成立。
6. 只有 `1d + 2d + 5d` 都确认后，再决定是否升级到更长窗口。
7. 更长窗口的第一档扩展应先作为独立 `extended-window probe` 运行，待 `session_summary.json` 完整落盘后，再决定是否并入正式证据链。
8. 如果 extended-window 伴随明显 rate-limit 或高错误率，应把“provider provenance 是否成立”和“运行稳定性是否足够”拆成两个结论，而不是混写为同一个 pass/fail。

## 6. 当前限制

即使加入这道闸门，single-provider session 仍然只是分支验证，不会自动改变下面两件事：

1. `MiniMax-M2.7` 相对 `MiniMax-M2.5` 的语义漂移事实。
2. 长窗口主矛盾仍然是低利用率与低部署深度并存。

因此，这条验证线的价值是“隔离 provider 变量”，不是“自动证明策略变好”。

截至 `2026-03-20`，该方案的 `1d`、`2d` 与 `5d` 阶段都已完成，详见 [single-provider-session-probe-20260320.md](./single-provider-session-probe-20260320.md)。

同日补充：

1. `2026-02-02..2026-02-10` 的第一档 `extended-window probe` 已完成，`session_summary.json`、`daily_events.jsonl` 与 `pipeline_timings.jsonl` 均已落盘。
2. 其 `llm_route_provenance` 继续确认 `fallback_attempts=0`、`fallback_observed=false`、`providers_seen=["MiniMax"]`、`models_seen=["MiniMax:MiniMax-M2.7"]`、`routes_seen=["MiniMax:default"]`。
3. 但同一 provenance 也记录了 `attempts=325`、`successes=142`、`errors=183`、`rate_limit_errors=23`，说明这档扩窗应写成“single-provider provenance 成立，但稳定性受限流与错误压力影响”。
4. 因此它现在可以并入正式证据链，但只能作为“provider 隔离成立”的扩窗样本，不能被表述成高稳定度 clean run。

## 7. 相关文档

1. [llm-routing-and-minimax-config-20260319.md](./llm-routing-and-minimax-config-20260319.md)
2. [w2_minimax_m2_7_branch_decision_gate_20260320.md](./w2_minimax_m2_7_branch_decision_gate_20260320.md)
3. [w3_data_readiness_check_20260320.md](./w3_data_readiness_check_20260320.md)
4. [single-provider-session-probe-20260320.md](./single-provider-session-probe-20260320.md)
