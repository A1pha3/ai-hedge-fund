# 2026-03-18 更长窗口验证计划

## 1. 目标

P2-3 的目标不是立刻把 paper-trading 窗口随意拉长，而是在不破坏当前研究口径的前提下，定义一套可执行、可停止、可比较的更长窗口验证方案。

这里的核心约束有三条：

1. 当前默认基线仍固定为 `paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317`，不因为新窗口出现就替换掉它。
2. benchmark guardrail、taxonomy、refresh protocol 继续沿用现有研究结论，不因扩大窗口而重置。
3. P2-3 只定义验证计划与产物格式，不重开 runtime 规则修改。

## 2. 当前已知边界

### 2.1 已固定的锚点

1. 研究基线窗口：`2026-02-02 .. 2026-03-04`
2. benchmark 锚点：`20260224 / 600519`、`20260226 / 600519`、`20260226 / 300724`
3. mechanism 锚点：`603993`、`300065`、`688498`
4. conflict / suppression 锚点：`600988`、`000426`、`000960`、`300251`、`300775`、`600111`、`300308`

### 2.2 当前覆盖缺口

截至 `2026-03-18`，仓库里可直接复用的长窗口 replay 仍高度集中在 `2026-02-02 .. 2026-03-04`，另外只有一个较短参考窗口 `2026-02-17 .. 2026-02-28`。

这说明当前剩余问题是“分布覆盖不足”，不是“验证框架缺失”。

### 2.3 数据就绪约束

本地 `data/stock/daliy` 目录当前只明确可见到 `20260303` 的选股文件，因此 P2-3 不能把 `2026-03-14` 或更晚日期直接当作默认可执行窗口。

因此，计划必须把“数据就绪检查”放在第一步，而不是先写死一个无法复现的未来窗口。

## 3. 计划结构

为避免把 frozen replay、live pipeline 和未来扩窗结果混在同一个语义层，P2-3 采用三层结构。

### 3.1 Layer A：固定锚点窗口

用途：保留当前研究基线，作为所有后续扩窗的参考坐标。

固定 run：

1. `baseline_frozen_anchor`
   - source: `paper_trading_window_20260202_20260304_reentry_confirm_validation_20260317`
   - role: `research baseline`
   - mode: `frozen_current_plan_replay`

规则：

1. Layer A 永远不被新窗口替代。
2. validation scoreboard 中的 `baseline` 继续指向这一 run。
3. 所有新窗口都只允许说“相对于锚点更好/更差/不可比较”，不允许直接改写锚点身份。

### 3.2 Layer B：同窗 bridge run

用途：把“窗口变化”与“执行模式变化”拆开。

这是 P2-3 最关键的一步，因为当前锚点是 frozen replay，而未来扩窗天然更接近 live pipeline。如果没有 bridge run，后续结果很容易把 runtime 波动、模型路由差异、窗口分布差异混在一起。

建议新增同窗 bridge run：

1. `bridge_live_anchor`
   - target window: `2026-02-02 .. 2026-03-04`
   - role: `bridge comparison`
   - mode: `live_pipeline`
   - purpose: 只用于建立“同窗 frozen vs live”差值，不用于替换 baseline

对 Layer B 的判定规则：

1. 如果 `bridge_live_anchor` 破坏 `20260226 / 300724` re-entry guardrail，则记为 `bridge_fail`，后续扩窗仍可继续做观测，但不得把 live 结果提升为默认口径。
2. 如果 `bridge_live_anchor` 通过 benchmark guardrail，才允许把未来 live 窗口与它并排比较。
3. Layer B 的存在，是为了让未来窗口至少有一个 live 同语义参照物，而不是让 frozen baseline 直接去和 live 新窗口硬比。

### 3.3 Layer C：扩展窗口

用途：观察当前口径在更长时间分布下是否仍保持 guardrail、deployment、taxonomy 的稳定性。

对每个新窗口，建议保留成对产物：

1. `window_X_live`
   - 先运行真实 `live_pipeline`
2. `window_X_frozen_replay`
   - 立刻基于 `window_X_live/daily_events.jsonl` 做同窗 frozen replay

这样做的目的不是重复跑一次，而是分离两个问题：

1. live 结果是否可接受
2. 同一窗口下，计划质量与执行噪声分别贡献了多少差异

## 4. 新窗口定义

P2-3 先定义一条窗口阶梯，而不是一次性拉成超长整窗。

### 4.1 W0 锚点窗口

1. `W0 = 2026-02-02 .. 2026-03-04`
2. 身份：固定锚点，不重跑 frozen baseline，只补 bridge live

### 4.2 W1 前向扩展窗口

目标：在保持起点不变的前提下，向后扩 7 到 10 个交易日。

默认目标：

1. `W1_target = 2026-02-02 .. 2026-03-14`

执行回退规则：

1. 如果 `2026-03-14` 前的数据未完全就绪，则把终点回退到 `2026-03-04` 之后第一个“数据完整、可重放、可生成 summary”的交易日。
2. 如果 `2026-03-04` 之后没有完整连续数据，则 W1 暂缓，不跳做 W2。

2026-03-19 补充约束：

1. 如果 W1 使用 `MiniMax-M2.7`，则必须作为独立验证分支单列，不并入当前 `MiniMax-M2.5` 主表。
2. W1 的解释必须同时引用 [m2-5-vs-m2-7-bridge-summary-20260319.md](./m2-5-vs-m2-7-bridge-summary-20260319.md) 与 [llm-routing-and-minimax-config-20260319.md](./llm-routing-and-minimax-config-20260319.md)。
3. 若运行期间出现 provider fallback、非结构化 JSON 重试或统计口径混杂，W1 只能记为 bridge/probe，不得提升为新的可比基线。

### 4.3 W2 对称扩展窗口

目标：在 W1 可执行之后，再向前补 7 到 10 个交易日，验证当前结论是否只是在 `2026-02` 初段成立。

默认目标：

1. `W2_target = 2026-01-20 .. W1_end`

执行回退规则：

1. 如果 `2026-01-20` 附近数据不完整，则向后收缩到最早可连续执行的交易日。
2. 若早段数据质量显著低于锚点窗口，W2 仅保留为 `data_gap_probe`，不进入 scoreboard 主表。

2026-03-19 运行补充：

1. 已启动 `paper_trading_window_20260120_20260313_w2_live_m2_7_20260319` 作为 `MiniMax-M2.7` 分支 W2 live 探针。
2. 当前运行已确认 `2026-01-20`、`2026-01-21` 段并非数据缺口，但终端输出中反复出现 `MiniMax limited, switching to Volcengine Ark:doubao-seed-2.0-pro`。
3. 该 W2 live 已完成落盘，墙钟耗时约 `2h43m09s`；`pipeline_timings.jsonl` 显示主要耗时不在数据段，而在长窗口下的 post-market fast-agent 路径。
4. 同窗 `paper_trading_window_20260120_20260313_w2_frozen_replay_m2_7_20260319` 已完成，且与 live 在 `performance_metrics`、`daily_event_stats`、期末组合价值和最近 5 个交易日资金曲线尾段上完全一致。
5. 已确认事件包括：`603993` 于 `2026-02-02` hard stop 退出、`300724` 于 `2026-02-05` hard stop 退出，`601600` 在窗口末仍持有 `400` 股；这些事件在 W2 live / frozen 中保持一致。
6. 由于 provider fallback 事实在 live 期间已经成立，本轮 W2 的最终归档口径应是 `fallback_contaminated_probe`，而不是 clean validation；它可以进入分支记录，但不能提升为新的可比主表基线。
7. 因此 W2 已从 `branch_probe_in_progress` 收口为“强 replay 对齐但路由受污染”的分支探针，后续若进入 W3，必须先解决 provider 污染和长窗口成本问题。
8. 之后又完成 `paper_trading_window_20260120_20260313_w2_live_m2_7_clean_rerun_20260319` strict rerun；`session_summary.json.llm_route_provenance` 显示 `rate_limit_errors=0`、`fallback_attempts=0`、`contaminated_by_provider_fallback=false`。
9. 这条 clean rerun 证据应解释为“strict default-route clean / no provider fallback contamination”，而不是“整个 session 没有其它 provider”。本次 metrics summary 仍记录到 `Volcengine` 与 `Zhipu`，说明系统原生多 provider 路由仍在，只是没有发生 fallback 污染。
10. clean rerun 的摘要指标为：`Return=-1.6097%`、`Final Value=98390.3041`、`Sharpe=-2.3683`、`Max Drawdown=-2.6003%`、`day_count=33`、`executed_trade_days=5`、`total_executed_orders=6`。
11. 因此 W2 现在应保留两条并存证据：`fallback_contaminated_probe` 与 `clean strict-route validation`；前者回答 contaminated live 是否可 replay，后者回答默认路由能否在长窗口下无 provider fallback 地跑完。
12. 两条证据都只属于 `MiniMax-M2.7` 分支记录，不改变 `MiniMax-M2.5` baseline 仍为主基线的事实。

### 4.4 W3 非重叠 holdout 窗口

目标：拿一个与锚点窗口不重叠的新分布做 holdout，而不是永远只在同一批日期上滚动。

默认目标：

1. `W3_target = W1_end + 1 trading day .. W1_end + 15 to 20 trading days`

执行规则：

1. W3 只在 W1 完成且 benchmark guardrail 未出现新增破坏时才启动。
2. W3 不要求与 W0 有完全相同的 ticker 分布，但必须继续用同一份 taxonomy 和 refresh protocol 解释结果。

2026-03-20 决策门槛补充：

1. W2 已形成两条并存证据：`fallback_contaminated_probe` 与 `clean strict-route validation`，详见 [w2_minimax_m2_7_branch_decision_gate_20260320.md](./w2_minimax_m2_7_branch_decision_gate_20260320.md)。
2. 若进入 W3，默认应继承 clean strict-route 口径，而不是继续把 contaminated live 作为主验证线扩窗。
3. W3 的结论措辞必须延续同一限制：`clean = no provider fallback contamination`，不等于 `single-provider-only session`。
4. 若 W3 仍保持平均资金利用率低于 `10%` 且没有新增高质量机制样本，则停止继续扩窗，优先回到候选生成、持仓生命周期和组合构造问题。
5. 同日的数据就绪检查已确认本地 `data/stock/daliy/` 目前没有形成 `2026-03-13` 之后连续交易日覆盖，因此 W3 当前状态应记为 `data_not_ready`，详见 [w3_data_readiness_check_20260320.md](./w3_data_readiness_check_20260320.md)。
6. 同日已先后完成 `2026-02-02` 单日 probe、`2026-02-02..2026-02-03` 两日 rerun 与 `2026-02-02..2026-02-06` 五日 rerun，三者都显示 `providers_seen=["MiniMax"]`、`routes_seen=["MiniMax:default"]`；说明 session 级单 provider 闸门已在 `1d + 2d + 5d` 窗口下成立，后续若继续推进这条线，应把它视为独立分支继续扩窗，而不是直接把它混入 W3 结论。

## 5. 统一比较口径

P2-3 的关键不是窗口多，而是比较口径单一。

所有 W0/W1/W2/W3 结果都必须固定输出以下字段：

1. `Return`
2. `Final Value`
3. `Sharpe`
4. `Max Drawdown`
5. `Avg Invested`
6. `Peak Invested`
7. `Peak Single Name`
8. `Avg Layer B`
9. `Avg Watchlist`
10. `Avg Buy Order`
11. `Main Buy Blockers`
12. `Main Watch Blockers`
13. `Trade Days / Orders`
14. `Avg Total Day Sec`
15. `Ticker Execution Digest`
16. `Guardrail Status`
17. `Taxonomy Status`

另外固定五条比较规则：

1. `initial_capital` 统一为 `100000`。
2. `tickers` 参数默认留空，不允许为某个窗口单独定制 tracking universe。
3. live run 的 model provider / model name 必须显式记录；不同模型路由不得直接进同一主表横比。
4. frozen replay 与 live pipeline 的 runtime 耗时只做附注，不做优劣判断主依据。
5. benchmark / taxonomy 结论继续人工判定，不自动从 JSON 汇总里推断。

## 6. 产物约定

每个新窗口至少要落四类产物：

1. `data/reports/<window_run>/session_summary.json`
2. `data/reports/<window_run>/daily_events.jsonl`
3. `data/reports/<window_run>/pipeline_timings.jsonl`
4. 一份基于 P2-1 模板的 replay 摘要文档

建议命名：

1. `paper_trading_window_<start>_<end>_bridge_live_anchor`
2. `paper_trading_window_<start>_<end>_validation_live`
3. `paper_trading_window_<start>_<end>_validation_frozen_replay`

建议执行顺序：

1. 先跑 live
2. 再基于 live 的 `daily_events.jsonl` 生成同窗 frozen replay
3. 再更新 replay summary
4. 再决定是否把该窗口加入 validation scoreboard
5. 最后才按 refresh protocol 刷新 historical edge 分诊

## 7. 停止条件

P2-3 不是无限滚动任务，必须显式定义停止条件。

满足以下任一条件即可停止向下一层窗口扩展：

1. 数据就绪失败：目标窗口内缺少连续可执行数据，导致 summary 或 daily events 无法稳定生成。
2. guardrail 失败：新窗口出现 benchmark 级误放，尤其是重新触发 `20260226 / 300724` 类回补破坏。
3. 可比性失败：新窗口使用了不同模型路由、不同 universe 或缺失关键 artifacts，导致结果无法放回 scoreboard。
4. 样本增益不足：连续两个新窗口都没有产生新的 clean near-threshold non-conflict 对象，且平均利用率仍低于 `20%`，则暂停扩窗，把重心切回候选生成与 edge 扩库。
5. taxonomy 无法归类：出现新的高影响行为，但无法落到现有 benchmark / mechanism / conflict-suppression / observation 体系，则先新开专项，不继续机械扩窗。

## 8. 最小执行清单

如果只做最小可用版本，P2-3 应按下面顺序执行：

1. 检查 `2026-03-04` 之后是否存在连续、可重放、可汇总的数据。
2. 在 `W0` 上补一条 `bridge_live_anchor`。
3. 若数据就绪，优先执行 `W1_live` 和配套的 `W1_frozen_replay`。
4. 为 `W1` 产出一份符合 P2-1 模板的 replay 摘要。
5. 仅当 `W1` 通过 guardrail 且可比性成立时，再进入 `W2` 或 `W3`。
6. 若继续推进 provider 隔离验证，则以 [single-provider-session-probe-20260320.md](./single-provider-session-probe-20260320.md) 为当前已验证起点，在 `1d -> 2d -> 5d` 已成立的前提下，再决定是否继续向更长窗口扩展，而不是直接把 single-provider 结论并入 W3。

## 9. 当前收口

截至 `2026-03-18`，P2-3 先收口为以下结论：

1. 更长窗口验证现在缺的不是模板，而是“数据就绪检查 + bridge run + 扩窗顺序”。
2. 当前默认基线仍是 `W0 frozen anchor`，不会因为后续 live 窗口出现而被直接替换。
3. 更长窗口验证必须先解决语义对齐问题，再扩时间长度；否则 scoreboard 会失去可比性。
4. 截至 `2026-03-20`，W3 尚未进入运行阶段，原因不是 W2 口径未收口，而是本地扩窗数据尚未就绪。

## 10. 关联文档

1. [validation-scoreboard-20260318.md](./validation-scoreboard-20260318.md)
2. [historical-edge-refresh-run-log-20260318.md](./historical-edge-refresh-run-log-20260318.md)
3. [replay-summary-template-20260318.md](./replay-summary-template-20260318.md)
4. [replay-artifact-api-20260318.md](./replay-artifact-api-20260318.md)
5. [historical-edge-date-coverage-matrix-20260318.md](./historical-edge-date-coverage-matrix-20260318.md)
6. [paper-trading-reentry-validation-20260317.md](./paper-trading-reentry-validation-20260317.md)
7. [w3_data_readiness_check_20260320.md](./w3_data_readiness_check_20260320.md)
8. [single-provider-session-probe-20260320.md](./single-provider-session-probe-20260320.md)
