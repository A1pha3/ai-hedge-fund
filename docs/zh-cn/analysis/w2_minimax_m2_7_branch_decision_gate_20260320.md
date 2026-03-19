# W2 MiniMax-M2.7 Branch Decision Gate

## 1. 文档目的

本页把 W2 的两条并存证据收束成同一张决策页，回答三个问题：

1. contaminated probe 和 clean strict-route validation 各自证明了什么。
2. 两条证据之间哪些指标发生了真实变化，哪些只是口径差异。
3. 进入 W3 之前，当前分支最合理的下一步是什么。

本页不是新的 baseline 结论页，而是 W2 收口后的 branch gate。

## 2. 两条 W2 证据的职责边界

| 证据 | 产物目录 | 回答的问题 | 不能回答的问题 |
| --- | --- | --- | --- |
| `fallback_contaminated_probe` | `data/reports/paper_trading_window_20260120_20260313_w2_live_m2_7_20260319` + frozen replay | contaminated live 是否可以被 frozen 强一致复验 | 默认路由是否 clean；session 是否 single-provider |
| `clean_strict_route_validation` | `data/reports/paper_trading_window_20260120_20260313_w2_live_m2_7_clean_rerun_20260319` | 在 `LLM_DISABLE_FALLBACK=true` 下，默认路由是否能无 provider fallback 污染地完整跑完 W2 | `MiniMax-M2.7` 是否可替代 M2.5 baseline；session 是否 MiniMax-only |

因此，W2 当前不是“二选一只保留一条”，而是两条证据并存、分别回答不同问题。

## 3. 核心对照

| 指标 | W2 contaminated | W2 clean strict-route | 变化解释 |
| --- | --- | --- | --- |
| Return | `-2.8223%` | `-1.6097%` | clean rerun 更好，但仍为分支结果 |
| Final Value | `97177.7047` | `98390.3041` | clean rerun 期末净值更高 |
| Sharpe | `-3.6660` | `-2.3683` | clean rerun 风险调整后表现改善 |
| Max Drawdown | `-2.9943%` | `-2.6003%` | clean rerun 回撤略浅 |
| Avg Invested | `7.0958%` | `5.9666%` | clean rerun 净值改善不是靠更高利用率堆出来的 |
| Peak Single Name | `14.8285%` | `14.8285%` | 单票峰值约束没有变化 |
| Final Cash Ratio | `94.2044%` | `81.8285%` | clean rerun 期末部署更深，但仍偏保守 |
| Day Count | `33` | `33` | 窗口完全同口径 |
| Executed Trade Days | `6` | `5` | clean rerun 少一个执行日 |
| Total Executed Orders | `7` | `6` | clean rerun 少一笔成交 |
| Avg Layer-B | `2.1212` | `2.1212` | 候选层规模未变 |
| Avg Watch | `0.4848` | `0.4848` | watchlist 密度未变 |
| Avg Buy | `0.1212` | `0.1212` | buy order 密度未变 |
| Avg Day Sec | `296.59s` | `182.73s` | clean rerun 更快，且无 provider fallback 污染 |

## 4. 当前最重要的语义结论

### 4.1 contaminated W2 已经证明的东西

1. `MiniMax-M2.7` 分支在 W2 长窗口下可以形成强 replay 对齐。
2. live 与 frozen 在 contaminated run 上的对齐强度已经高到足以排除“只是偶然近似”。
3. 这条证据主要支持 runtime 可复验性，不支持 clean route 结论。

### 4.2 clean W2 已经证明的东西

1. `LLM_DISABLE_FALLBACK=true` 可以把 W2 长窗口运行收束为 fail-closed、可审计的 strict-route artifact。
2. `llm_route_provenance` 已足够支撑 `fallback_attempts=0`、`contaminated_by_provider_fallback=false`。
3. 这条证据主要支持默认路由 clean，不支持 `MiniMax-only session` 结论。

### 4.3 仍然没有被证明的东西

1. `MiniMax-M2.7` 没有被证明可替换当前 `MiniMax-M2.5` baseline。
2. clean W2 没有把系统证明成 whole-session single-provider。
3. W2 也没有解决当前长窗口主矛盾：低利用率与低部署深度并存。

## 5. 为什么 clean 比 contaminated 更适合当 W3 前置 gate

如果 W3 的目标是继续验证更长窗口下的 strict-route 行为，而不是只复验 contaminated live，那么 clean W2 更适合作为进入 W3 的前置 gate，原因有三点：

1. 它已经回答了“默认路由能否不靠 provider fallback 跑完整个窗口”。
2. 它保留了 artifact-level provenance，可继续沿用相同审计口径。
3. 它把 contaminated run 里的主要混淆变量先剥掉了，W3 的解释成本会更低。

但这不意味着 contaminated W2 可以丢弃，因为 contaminated W2 仍然是 replay 强一致性的最好证据。

## 6. W3 前的决策门槛

进入 W3 之前，建议先接受下面三条门槛：

1. W3 只沿用 clean strict-route 口径，不再把 contaminated live 当成主验证支线继续扩窗。
2. W3 运行说明里必须继续明确：clean 的含义是 `no provider fallback contamination`，不是 `MiniMax-only session`。
3. 若 W3 仍出现平均资金利用率长期低于 `10%` 且没有新增高质量机制样本，则暂停继续扩窗，把重心切回候选生成、生命周期和组合构造。

## 7. 当前建议

当前最稳妥的建议不是重新讨论 W2 是否“算通过”，而是直接冻结下面的口径：

1. W2 contaminated：作为 `replay-consistency evidence` 保留。
2. W2 clean：作为 `strict-route gate evidence` 保留。
3. 若继续做 W3，默认继承 clean strict-route 条件。
4. 若后续目标改成 session 级 single-provider 验证，则应新开一条独立实验线，不复用当前 clean 口径。

## 8. 相关文档

1. [w2_minimax_m2_7_live_frozen_contaminated_probe_20260319.md](./w2_minimax_m2_7_live_frozen_contaminated_probe_20260319.md)
2. [w2_minimax_m2_7_clean_strict_route_validation_20260320.md](./w2_minimax_m2_7_clean_strict_route_validation_20260320.md)
3. [validation-scoreboard-20260318.md](./validation-scoreboard-20260318.md)
4. [longer-window-validation-plan-20260318.md](./longer-window-validation-plan-20260318.md)
