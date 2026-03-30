# 0330 BTST 研究执行清单

文档日期：2026 年 3 月 30 日  
适用对象：负责 0330 BTST 专项审阅、变体实验、研究排期和结论收口的研究员与研究负责人。  
文档定位：把 [README.md](./README.md) 里的路线文，拆成可以直接执行、直接审阅、直接停损的阶段化动作单。

---

## 1. 使用边界

在开始任何实验前，先统一 4 条边界：

1. 0330 路线文里的核心判断来自多份报告的综合阅读，不是单一报告中的严格 A/B 对照。
2. 本专题中的 false negative，统一指当前规则下被判为 `rejected`、`blocked` 或仅保留为观察层样本，但至少满足以下之一：① T+1 `next_high_return` 达到研究组设定的 intraday 空间门槛；② T+1 `close` 为正，且延续性没有明显塍填；③ 同类 frontier / 冲突 / 入口语义在滚动窗口中反复出现。完整操作性定义见 [README.md §4.6](./README.md#46-为什么-false-negative-挖掘比继续盯-selected-更重要)。
3. `T+2 close` 只作为隔夜 continuation 的 post-hoc 代理，不得被写成“系统已经还原真实可执行 BTST 收益”。
4. Phase 2 之前禁止多主题联动实验；每轮只能动一类机制。

---

## 2. 固定输入包

每位研究员在启动 0330 专项前，至少应先固定以下输入：

1. `data/reports/btst_next_day_trade_brief_20260327_for_20260330_20260329.md`
2. `data/reports/short_trade_blocker_analysis_baseline_full_20260329.json`
3. `data/reports/pre_layer_short_trade_outcomes_layer_b_boundary_current_window_20260329.json`
4. `data/reports/pre_layer_short_trade_outcomes_short_trade_boundary_current_window_20260329.json`
5. `data/reports/short_trade_boundary_coverage_variants_current_window_20260329.md`
6. `data/reports/profitability_subfactor_breakdown_current_window_20260327.json`
7. `docs/zh-cn/factors/28-paper-trading-tday-t1-timing-guide.md`
8. `docs/zh-cn/product/arch/arch_optimize_implementation.md`

如果上述输入包缺任一件，本轮结论只能记为“暂不完备”，不得进入默认升级讨论。

---

## 3. 0330 专项优先级顺序

| 优先级 | 任务 | 目标 | 必须输出 |
| --- | --- | --- | --- |
| P0 | 冻结 baseline | 统一样本口径与输入包 | 微窗口样本总表、baseline 指标页、问题清单 |
| P1 | false negative dossier | 明确系统漏掉了什么 | 主入场票表、观察票表、false negative 表 |
| P2 | breakout 语义修正 | 先修最主要的 admission 主矛盾 | 单主题变体报告、blocker 迁移表 |
| P3 | profitability 条件软化 | 验证慢变量是否过强压制 | 条件化软惩罚对照表、行业重叠说明 |
| P4 | 双名单 contract 收紧 | 把会选和会买分开 | 主入场票 / 观察票规则说明、report-layer 与 execution-layer 对照 |
| P5 | structural conflict 定点审查 | 只救高价值 blocked 样本 | case-based rescue 记录、changed_non_target_case_count 说明 |

0330 当前建议的真实顺序是 `P0 -> P1 -> P2 -> P3 -> P4 -> P5`。如果 P1 还没完成，就不要跳去讨论 profitability 或 structural conflict。

这里再固定一条阶段边界：在 P2-P4 尚未证明当前窗口能够稳定释放可解释新增样本前，禁止把开盘消化、盘中确认、结构空间、板块共振、催化兑现节奏当作新的 admission 主线。它们只能在后续作为独立的 `entry-quality factor pack` 使用，用于主入场票 / 观察票分层、执行确认与风险权重。

### 3.1 截至 2026-03-30 夜间的当前执行状态

以下事项已经在当前窗口真实复跑中完成，不应再按“待探索”处理：

1. P0 / P1 已完成，固定产物见 `data/reports/p0_baseline_freeze_20260330.json`、`data/reports/p1_false_negative_priority_summary_20260330.json`。
2. Top 3 case-based 执行已完成，汇总见 `data/reports/p2_top3_experiment_execution_summary_20260330.json`。
3. `001309` 已确认是当前唯一 `primary_controlled_follow_through`：`2/2` 目标样本完成迁移、零 spillover、`next_close_positive_rate=1.0`。
4. `001309` 的下一步也已被收紧为“继续滚动复核，而不是默认升级”：`data/reports/p4_primary_roll_forward_validation_001309_20260330.json` 已确认它仍缺跨窗口稳定复现证据。
5. `300383` 只应继续保留为 `shadow_keep`，不应因为次日表现为正就抢占 primary 位置。
6. `300383` 当前还是整个 frontier 里唯一的 threshold-only 低成本 rescue；`data/reports/p4_shadow_entry_expansion_board_300383_20260330.json` 已明确同规则扩样条件尚不成立。
7. `300724` 只应继续保留为 `structural_shadow_hold`；后验 `next_close_return_mean=-0.0443`，因此不得升级成窗口级 structural release 依据。
8. 如果研究团队要继续推进 shadow lane，下一条路线不应再复制 `300383`，而应改走 recurring frontier：`data/reports/p4_shadow_lane_priority_board_20260330.json` 已把 `002015` 定义为 close-continuation shadow 候选，把 `600821` 定义为 intraday control。
9. `001309` 当前的真实缺口也已独立成报告：`data/reports/p6_primary_window_gap_001309_20260330.json` 已确认至少还缺 1 个新增独立窗口，不能把“继续 primary roll-forward”误写成“已经具备默认升级条件”。
10. recurring shadow 也已有正式 runbook：`data/reports/p6_recurring_shadow_runbook_20260330.json` 已明确 `002015` 和 `600821` 的 close / intraday 分工。
11. `001309` 的滚动验证现在也已从“原则”收紧到“复跑命令级 runbook”：`data/reports/p7_primary_window_validation_runbook_001309_20260330.json` 已把当前所有已发现窗口逐个扫描，确认除了 `20260323_20260326` 外暂无第二个独立 short-trade window，因此当前剩余工作已经是未来窗口数据依赖，而不是方法缺口。
12. `300383` 的扩样扫描也已补成独立板：`data/reports/p7_shadow_peer_scan_300383_20260330.json` 已把全部 peer 按 threshold-only / penalty-coupled 分开，确认当前不存在第二只 same-rule peer，因此它只能固定为单票 shadow，扩 lane 时必须改走 recurring frontier。
13. `300724` 的 structural freeze 现在也已补成正式 runbook：`data/reports/p8_structural_shadow_runbook_300724_20260330.json` 已把 blocked cluster 的 rescue ranking、单票 targeted release 和负的 post-release outcome 合并成统一 stop-condition，明确不得重开 cluster-wide structural 放松。
14. 结合 [docs/zh-cn/product/arch/arch_optimize_implementation.md](docs/zh-cn/product/arch/arch_optimize_implementation.md) 的 live 收口结果，旧的 `rejected_layer_b_boundary_score_fail=23` 已不再是当前默认路径的在线主簇：dedicated short-trade builder 已把 shared `layer_b_boundary` rejection 压到 `0`，并把默认 admission 基线稳定到 `short_trade_boundary + catalyst_freshness_min=0.00`。
15. 这也意味着当前执行清单里的 P2 不应再理解为“重新大范围扫描 admission floor”，而应优先理解为围绕 `short_trade_boundary` score frontier、`001309/300383` case-based lane 与 `300724` 结构冲突做单主题治理。
16. 微窗口闭环回归分析器与实证结论也已补齐，见 [btst_micro_window_regression_20260330.md](../../../../../data/reports/btst_micro_window_regression_20260330.md)：`2026-03-23` 到 `2026-03-26` baseline 的 `tradeable surface=0`、`false_negative_proxy_count=19`，而 `catalyst_floor_zero` 已把 closed-cycle actionable 提升到 `6` 且通过 guardrail；因此当前方法缺口已经收口，剩余工作主要是 future window 验证与 frontier 治理，而不是继续补“怎么做微窗口回归”这件事。

### 3.2 当前最应该推进的 3 项动作

1. 把 `001309` 推进到滚动窗口 follow-through 复核，但在新增独立窗口前不得讨论默认升级。
2. 把 `300383` 固定在 shadow queue；在出现第二只 threshold-only peer 且仍零 spillover 前，禁止按同规则扩样。
3. 若要继续扩 shadow lane，优先推进 `002015` 的 recurring shadow close 验证，并把 `600821` 保留为 recurring intraday control。
4. 把 `300724` 固定为单票 structural 观察样本，明确禁止 cluster-wide structural 放松。
5. 所有周会或评审里，必须先引用 `p6_primary_window_gap`、`p6_recurring_shadow_runbook` 和 `p8_structural_shadow_runbook`，防止再次把“证据缺口”“shadow 扩展资格”和“structural freeze 条件”混写。
6. 在当前 2026-03-30 证据边界内，文档里的方法设计、治理板、runbook、peer scan 已全部落齐；剩余未完成项只可能来自未来新增 paper_trading_window 数据，而不是当前路线仍有未定义动作。
7. 不要再把旧 `layer_b_boundary` 失败簇当作当前 live 路径的默认优化入口；除非未来窗口重新出现 admission 级大簇，否则当前优先级应停留在 score frontier 与结构性治理。
8. 在 coverage recovery 稳定前，不要继续堆新的放行因子；下一阶段如果推进开盘消化、盘中确认、结构空间、板块共振或催化兑现，只能以 `entry-quality factor pack` 的方式服务于双名单与执行确认。

---

## 4. 每个阶段的通过条件

### 4.1 P0：冻结 baseline

完成标准：

1. `selected / near_miss / blocked / rejected / false negative` 五类标签口径写成固定表述。
2. 2026-03-24、2026-03-25、2026-03-26、2026-03-27 四个收盘日都能对齐到同一张微窗口样本表。
3. brief、blocker、pre-Layer C outcome 三类报告之间的语义差异被显式写明。

停止条件：

1. 同一 trade_date 在不同报告中口径不一致，且未解释来源差异。
2. 研究员仍在混用“观察票”和“默认买入票”的含义。

### 4.2 P1：false negative dossier

完成标准：

1. 至少形成 3 张固定表：主入场票、观察票、false negative。
2. false negative 至少按以下三类之一归档：`score fail but high works`、`watch-only but tradable intraday`、`structural conflict but pattern recurs`。
3. 每张表都附带 T+1 机会指标，而不是只写最终是否赚钱。

停止条件：

1. 只拿 selected 样本讲故事，没有给出被漏样本的反例。
2. false negative 定义仍然依赖口头解释，不能落成固定口径。

### 4.3 P2：breakout 语义修正

完成标准：

1. 一轮只改 breakout 相关 admission / score 语义，不联动 profitability、penalty 或 execution proxy。
2. 新增样本 `> 0`。
3. `next_high_hit_rate@2% >= 0.5217`，`next_close_positive_rate >= 0.5652`。
4. 新增样本不能被单一 ticker 或单一行业完全垄断。
5. 若当前窗口沿用的是 dedicated short-trade builder 默认路径，则优先在 `short_trade_boundary_score_fail` frontier 内做单主题 release / promotion；只有当 admission 级失败簇重新出现时，才回到 floor 语义修正。

停止条件：

1. `next_high_hit_rate@2%` 与 `next_close_positive_rate` 同时跌破上述旧 `layer_b_boundary` 基线。
2. 样本虽然变多，但没有新增任何可归入 §7.4 定义的三类 false negative archetype（`score fail but high works`、`watch-only but tradable intraday`、`structural conflict but pattern recurs`）之一的样本。
3. 研究员试图在 `catalyst_freshness_min=0.00` 已通过完整窗口 live 验证后，重新启动无目标的大范围 admission floor 网格扫描。

### 4.4 P3：profitability 条件软化

完成标准：

1. 只允许在高 breakout / 高催化 / 强板块共振条件下做条件化软化，不允许全局取消 profitability。
2. 需要同时提交“放松后新增样本”和“未放松样本”的行业对照。
3. false negative 数下降，但机会指标不低于 P2 通过时的结果。

停止条件：

1. 软化后主要新增的是低机会质量样本。
2. 软化逻辑无法解释为什么只在特定行业生效。

### 4.5 P4：双名单 contract 收紧

完成标准：

1. 主入场票与观察票在 report 层与 execution 层都有明确语义。
2. `near_miss` 不再被默认解释成“轻度 selected”。
3. 所有研究记录都能明确区分“值得盯盘”和“值得执行”。
4. 开盘消化、盘中确认质量、结构空间、板块共振、催化兑现节奏被明确归类为独立的 `entry-quality factor pack`，且只服务于主入场票 / 观察票分层、执行确认或风险权重，不回写成 broad admission 放行规则。

停止条件：

1. 观察票仍然被研究员直接写进默认买入清单。
2. 主入场票与观察票的执行动作没有分开定义。
3. 研究员把 `entry-quality factor pack` 重新写回 admission 主线，导致“放出票”和“买点质量”两件事再次混在一起。

### 4.6 P5：structural conflict 定点审查

完成标准：

1. 只做 case-based rescue，不做全局放松。
2. 每个 rescue 结论都要附 `changed_non_target_case_count`。
3. 先审高价值 blocked 样本，再审一般 blocked 样本。

停止条件：

1. 通过救某一票连带放出大量非目标样本。
2. 需要联动多条 penalty 才能勉强成立，却没有滚动窗口重复证据。

---

## 5. 每轮实验的固定交付件

每轮单主题实验结束后，都必须交付以下 6 件东西：

1. 变体说明：本轮只改了哪一类机制，明确写出未改的机制。
2. 指标页：Coverage、Opportunity、Execution、Stability、Learnability 五组指标。
3. blocker 迁移表：失败簇从哪里迁移到哪里。
4. false negative 更新页：新增了哪类可解释样本，或明确写“无新增”。
5. 风险说明：本轮结论是否仍受 sample size、report family 或 proxy 边界限制。
6. 决策结论：`go`、`shadow only`、`rollback` 三选一。

如果交付件不完整，本轮实验默认记为 `shadow only`。

---

## 6. 周会汇报时只回答 5 个问题

1. 这一轮到底多放出了多少真正值得研究的票。
2. 这些新增票是否仍然给出 T+1 机会空间。
3. 失败簇是否从 admission 主问题迁移到了更可解释的 frontier 主问题。
4. 这轮新增样本有没有形成新的 false negative archetype。
5. 这项变体应继续推进、保留为 shadow，还是立即回滚。

如果这 5 个问题有任意 2 个答不清，这轮结论就不应进入默认升级讨论。

---

## 7. 本清单与路线文 Phase 的对应关系

本清单覆盖 [README.md](./README.md) 中 Phase 0–2 的可执行层，具体映射如下：

| 本清单优先级 | 路线文 Phase | 路线文主线 / 工作流 |
| --- | --- | --- |
| P0 冻结 baseline | Phase 0 (§9.1) | — |
| P1 false negative dossier | Phase 1 (§9.2) | 工作流 B (Quality) |
| P2 breakout 语义修正 | Phase 2 (§9.3) — 单主题变体第 1 轮 | 工作流 A (Coverage) / 主线一 (§7.1) |
| P3 profitability 条件软化 | Phase 2 (§9.3) — 单主题变体第 2 轮 | 工作流 D (慢变量) / 主线二 (§7.2) |
| P4 双名单 contract | Phase 2 (§9.3) — 单主题变体第 3 轮 | 工作流 C (执行确认) / 主线三 (§7.3) |
| P5 structural conflict | Phase 2 (§9.3) — 单主题变体第 4 轮 | 路线文 §9.3 细项 4 |

Phase 3（滚动窗口验证，§9.4）和 Phase 4（执行确认增强，§9.5）的未来数据执行本身仍需后续窗口继续推进；但截至 2026-03-30，它们的治理、runbook 与 stop condition 支撑件已经在本专题内补齐，不再属于“方法未定义”。
