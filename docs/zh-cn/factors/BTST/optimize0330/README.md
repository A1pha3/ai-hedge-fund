# BTST 0330 优化路线设计文：从 coverage 修复到新因子挖掘

文档日期：2026 年 3 月 30 日  
适用对象：需要审阅 BTST 优化方向、评估实验优先级、安排研究排期的研究员、研究负责人、开发者、AI 助手。  
文档定位：把 2026-03-30 这次关于“候选太少、主入场票过窄、是否需要扩覆盖和挖新因子”的讨论，整理成一份可评审、可拆任务、可直接进入实验闭环的专项路线文档。

证据边界说明：本文同时引用单日 next-day brief、当前窗口 replay_input_validation baseline、pre-Layer C outcome 报告以及 profitability 子因子统计。除非特别注明，以下结论都应理解为跨报告族的方向性综合判断，而不是单一报告里的严格 A/B 对照。

建议搭配阅读：

1. [BTST 次日短线策略完整指南](../01-btst-complete-guide.md)
2. [BTST 调参与验证作战手册](../02-btst-tuning-playbook.md)
3. [BTST 当前窗口案例复盘手册](../08-btst-current-window-case-studies.md)
4. [BTST 优化决策树](../11-btst-optimization-decision-tree.md)
5. [BTST 命令作战手册](../13-btst-command-cookbook.md)
6. [Paper Trading T 日到 T+1 时序专题](../../28-paper-trading-tday-t1-timing-guide.md)
7. [Execution Bridge 专业讲解](../../24-execution-bridge-professional-guide.md)
8. [0330 BTST 研究执行清单](./01-0330-research-execution-checklist.md)

---

## 1. 这份文档要解决什么问题

这份文档重点回答 4 个问题：

1. 为什么 2026-03-27 的 BTST 结果里，2026-03-30 只出现了 1 只主入场票 `300757`，而这不应被直接解读成“市场里只有 1 只可做”。
2. 如何把“2026-03-24、25、26、27 收盘后选股，次日买入，再下一交易日卖出”的想法改造成更严谨的 BTST 验证框架。
3. 当前 BTST 优化主线到底应优先修 coverage、修 score frontier、修结构冲突，还是挖新因子。
4. 研究团队下一步应该按什么顺序推进，才能减少拍脑袋调参和小窗口过拟合。

阅读完本文档后，你应该能回答：

1. 当前 BTST 的主矛盾更偏 coverage 还是 quality。
2. 为什么只看“最终盈利”不足以评价 BTST 因子。
3. 为什么 `300757` 和 `601869` 的处理方式不同。
4. 为什么 profitability 在 BTST 场景下更适合作为软约束，而不是前置硬杀。
5. 下一轮实验应先做哪些最小改动，哪些动作应明确禁止。

---

## 2. 先讲结论：当前 BTST 的主问题不是没有票，而是放行太少

如果只保留最重要的结论，请先记住下面 10 条：

1. 当前 BTST 的核心问题更像 coverage 不足，而不是候选质量整体太差。
2. `300757` 作为 2026-03-30 的主入场票是合理的，但它的正确执行方式是 `next_day_breakout_confirmation`，而不是无脑开盘追价。
3. `601869` 作为 near-miss 观察票也合理，但它的语义是“继续盯盘确认”，不是默认买入。
4. 当前系统里“会选”与“会买”仍然是两层逻辑，不能混为一谈。
5. 2026-03-23 到 2026-03-26 的旧 baseline 主失败簇确实是 `rejected_layer_b_boundary_score_fail`，但这条 shared Layer B 失败链已经被当前 live short-trade builder 路径实质性消除；它现在更适合作为“为什么要分池”的历史诊断证据，而不是当前默认路径的主矛盾。
6. 当前 live 路径里，`short_trade_boundary` 已经成为真正的主候选源，且 `catalyst_freshness_min=0.00` 已完成完整窗口验证；因此下一轮主线不再是继续寻找第二条 admission floor，而是围绕新的 score frontier 与结构性 blocked 样本做治理。
7. breakout 语义过窄仍然是旧阶段的重要根因，但在 dedicated short-trade builder 与 catalyst-only 扩覆盖落地后，当前更活跃的 frontier 已经转向 `short_trade_boundary_score_fail` 与 `layer_c_bearish_conflict`，而不是继续回到 shared boundary 大范围扫阈值。
8. profitability 在 2026-03-23 到 2026-03-26 的更广义 Layer B 融合低分样本里表现出很强的压制性，且与 BTST 当前活跃行业高度重叠，因此需要从硬约束转向条件化惩罚，而不是直接照搬研究型目标的硬杀逻辑。
9. 你的“收盘选股，次日买入，再下一交易日卖出”方法是可行的，但必须拆成“机会质量验证”和“执行后收益验证”两层，不宜只看最终盈亏。
10. 下一轮优化不应该先做大网格乱扫，而应该先建立一套研究员可审阅的分层验证框架，再做单主题实验。

### 2.1 2026-03-30 夜间复跑后的当前状态

基于 `data/reports/p2_top3_experiment_execution_summary_20260330.json` 的真实复跑结果，0330 当前窗口的 case-based 结论已经进一步收紧：

1. `001309` 已完成 `2/2 near_miss -> selected`，且 `changed_non_target_case_count=0`、`next_high_return_mean=0.0510`、`next_close_return_mean=0.0414`、`next_close_positive_rate=1.0`，因此可正式视为当前唯一的 `primary_controlled_follow_through` 入口。
2. `300383` 仍然成立，但只能定义为 `shadow entry`：它是 `1/1 rejected -> near_miss`、零 spillover、次日 close 为正的低污染 threshold-only release，不过目前仍只有单样本，不应升级为默认 primary 口径。
3. `300724` 的 targeted structural release 只应继续停留在 `structural shadow hold`：虽然它能 `blocked -> near_miss` 且不污染其他样本，但真实后验表现是 `next_high_return_mean=-0.0070`、`next_close_return_mean=-0.0443`，因此不能外推成 cluster-wide structural 放松依据。
4. 但 `001309` 目前仍只具备当前窗口内的 `emergent_local_baseline` 证据：`data/reports/p4_primary_roll_forward_validation_001309_20260330.json` 已明确它仍缺 `distinct_window_count>=2` 的跨窗口复现，因此当前只能继续做 controlled roll-forward，不能进入默认升级讨论。
5. `300383` 的 shadow 语义也已经进一步收紧：`data/reports/p4_shadow_entry_expansion_board_300383_20260330.json` 证明它是当前整个 frontier 里唯一的 threshold-only 低成本 release，下一档样本都需要 stale / extension penalty 联动下调；因此它可以继续保留，但不能按同一规则做批量扩散。
6. 当 `300383` 的同规则扩样被封住后，下一条更合理的 shadow 扩展路线应切到 recurring frontier：`data/reports/p4_shadow_lane_priority_board_20260330.json` 已把 `002015` 收紧为 close-continuation shadow 候选，把 `600821` 收紧为 intraday control，而不是继续复制 `300383` 的单票 threshold-only 规则。
7. 现在连 `001309` 还缺什么证据也已经显式化：`data/reports/p6_primary_window_gap_001309_20260330.json` 已确认它目前不是缺主实验 guardrails，而是至少还缺 1 个新增独立窗口，因此现阶段最该补的是窗口证据而不是默认升级叙事。
8. recurring shadow lane 也不再只是排序关系：`data/reports/p6_recurring_shadow_runbook_20260330.json` 已把 `002015` 固定为 recurring shadow close 候选，把 `600821` 固定为 recurring intraday control，并明确两者不能被混写成同一条 shadow 规则。
9. `001309` 的后续动作现在也已被收紧成复跑命令级别：`data/reports/p7_primary_window_validation_runbook_001309_20260330.json` 已逐窗口扫描当前归档报告，确认除了 `20260323_20260326` 外并不存在第二个独立 short-trade window，因此当前未完成的只剩未来窗口数据本身。
10. `300383` 的扩样路径也不再只是“不要复制它”的口头判断：`data/reports/p7_shadow_peer_scan_300383_20260330.json` 已确认当前 peer 全部属于 penalty-coupled lane，没有第二只 threshold-only same-rule peer，所以 shadow 扩展必须改走 recurring frontier。
11. `300724` 的 structural lane 现在也已从“结论”补成“runbook”：`data/reports/p8_structural_shadow_runbook_300724_20260330.json` 已把窗口级 blocked cluster、单票 targeted release 与负的 post-release quality 一并收口，明确这条 lane 只能保持 `structural_shadow_hold_only`，只有未来新窗口出现新的高优先级 structural case 且 close continuation 转正，才允许重开评审。
12. 结合上游实施收口文档 [docs/zh-cn/product/arch/arch_optimize_implementation.md](docs/zh-cn/product/arch/arch_optimize_implementation.md)，0330 当前默认 live 路径还应再补一条事实：旧的 `layer_b_boundary` score-fail 簇在 dedicated short-trade builder 上已经降到 `0`，当前完整窗口 live 候选的 admission 主基线已经切换为 `short_trade_boundary + catalyst_freshness_min=0.00`。
13. 因而“下一轮最应该做的 3 件事”已经从泛化的 P2/P3/P5 讨论，进一步收敛为：等新增窗口数据出现后复跑 `001309` 的独立窗口验证；把 `300383` 固定为单票 shadow；再把 `002015 / 600821` 作为 recurring shadow 的 close 候选与 intraday 控制样本推进，而 `300724` 保持治理性冻结，同时不再回头重开 shared Layer B 池的大范围 floor 扫描。

---

## 3. 当前现状快照：0330 讨论的证据基础是什么

### 3.1 2026-03-27 单日 BTST 输出的直接结论

根据 `data/reports/btst_next_day_trade_brief_20260327_for_20260330_20260329.md`：

1. 2026-03-27 收盘后，2026-03-30 的 `short_trade_selected_count=1`，主入场票为 `300757`。
2. `short_trade_near_miss_count=1`，观察票为 `601869`。
3. `300757` 的 `preferred_entry_mode=next_day_breakout_confirmation`，说明它从设计上就不是开盘无条件追价票。
4. `601869` 的 `decision=near_miss`，语义是盘中跟踪，不是默认纳入买入清单。

这说明当前 brief / report 层已经表达出“主入场票 / 观察票”分层，只是放行范围太窄；下一步仍应把这套分层继续收紧为稳定的 execution contract，而不能只停留在人工解释层。

### 3.2 当前窗口主失败簇在哪里

根据 `data/reports/short_trade_blocker_analysis_baseline_full_20260329.json`：

1. 2026-03-23 到 2026-03-26 一共出现 32 个 short-trade 样本。
2. 其中 `selected=0`、`near_miss=0`、`blocked=5`、`rejected=27`。
3. 最大失败簇是 `rejected_layer_b_boundary_score_fail=23`。
4. 这 23 个样本都来自 `layer_b_boundary`，均值分数只有 `0.1323`。
5. 这组数据来自当前窗口的 replay_input_validation baseline，用来定位失败簇，不是与 3.1 同一个单日 brief 的直接 A/B 对照。

这表明旧路径下的主堵点位于 short-trade 边界供给与 pre-score 结构，而不是 Layer C 全面失灵。

但结合上游实施文档当前已收口的 live 证据，这里还必须加一条边界：这组 `rejected_layer_b_boundary_score_fail=23` 更适合作为“为什么短线不应继续与研究型 Layer B 共池”的历史诊断，而不是当前默认 live 路径的在线主堵点。当前 live builder 已把这类 shared boundary rejection 压到 `0`，因此后续研究不应再把主要精力放回 shared Layer B 候选池本身。

### 3.3 当前 coverage 与 quality 是什么关系

根据 `data/reports/pre_layer_short_trade_outcomes_layer_b_boundary_current_window_20260329.json`、`data/reports/pre_layer_short_trade_outcomes_short_trade_boundary_current_window_20260329.json`，以及上游实施文档已经收口的完整窗口 live admission 结果：

1. 旧的 `layer_b_boundary` 候选池有 23 个，`next_high_return_mean=0.0263`，`next_close_return_mean=0.0027`，`next_high_hit_rate@2%=0.5217`，`next_close_positive_rate=0.5652`。
2. 新的 `short_trade_boundary` 候选池只有 2 个，但 `next_high_return_mean=0.0829`，`next_close_return_mean=0.0498`，两项命中率都是 `1.0`。
3. 在完整窗口 live 路径里，默认 `short_trade_boundary + catalyst_freshness_min=0.00` 已把候选扩到 24 个，并给出 `near_miss=6`、`rejected_short_trade_boundary_score_fail=18`；对应 pre-Layer C outcome 为 `next_high_return_mean=0.0471`、`next_close_return_mean=0.0186`、`next_high_hit_rate@2%=0.75`、`next_close_positive_rate=0.7083`。

这里要先把证据边界说清楚：前两份 pre-Layer C outcome 报告用于比较两类 candidate source 的方向差异，不应误读为同一 baseline 下的严格 apples-to-apples A/B；而完整窗口 live admission 结果则回答了“当前默认短线 builder 路径是否已经把旧 shared boundary 问题收掉”。两类证据合起来，才能说明“方向已正确，但活跃 frontier 已经切换”。

结论很明确：

1. 旧池子覆盖够，但噪声偏大。
2. 新池子在最早的局部比较里质量高但覆盖塌缩，而在完整窗口 live builder 上已经恢复到可研究覆盖。
3. 当前最正确的优化目标不再是重新讨论 admission floor，而是维持这条 live admission 基线，并把优化重心切到 `short_trade_boundary` score frontier、recurring frontier 与结构性 blocked 样本。
4. 当前证据足以支持“admission 主线已切换”的方向判断，但统计把握仍有限，因此默认升级仍必须等待滚动窗口。

### 3.4 为什么不能指望简单调阈值救回来

根据 `data/reports/short_trade_boundary_coverage_variants_current_window_20260329.md` 与上游实施文档的完整窗口 live 收口结果：

1. 多个 boundary threshold 变体在当前候选池上都没有新增通过样本。
2. 19 个样本反复卡在 `breakout_freshness_below_short_trade_boundary_floor`。
3. 剩余样本主要卡在 `catalyst_freshness` 或 `volume_expansion`。
4. 但完整窗口 live 验证已经证明，`catalyst_freshness_min=0.00` 是当前唯一值得保留的 admission 扩覆盖基线；继续联动放松 volume floor 会明显拉低 close continuation 质量。

这说明旧阶段的问题不只是阈值高，而是 `breakout_freshness` 的定义或使用方式过窄；但在当前阶段，这条 admission 主线已经完成最小可用收口，因此不应再把“是否继续放 admission floor”当作最优先问题。

补充一条新的反证：`data/reports/btst_profile_frontier_20260330.md` 已把同一 0323-0326 closed-cycle 窗口下的 `default`、`staged_breakout`、`aggressive`、`conservative` 放到统一 outcome 面上比较，结果四个 profile 的 `tradeable surface` 都仍然是 `0`。这说明当前问题也不适合再理解成“换个 short-trade profile 就能推起来”，而应继续把主优化面收敛在 `score construction` 与 `candidate entry` 语义上。

再补一条更强的反证：`data/reports/btst_score_construction_frontier_20260330.md` 已把 `prepared_breakout_balance`、`catalyst_volume_balance`、`trend_alignment_balance` 三条正向 weight 变体放到同一 closed-cycle outcome 面上比较，结果三者依然全部是 `tradeable surface=0`，而 baseline false negative proxy 规模也没有缩小。这说明当前窗口里“只调正向分数权重”同样不是突破口。

当前窗口里真正新增解释力的是 `data/reports/btst_candidate_entry_frontier_20260330.md`：`weak_structure_triplet`、`semantic_pair_300502`、`volume_only_20260326` 都能过滤 `2026-03-26` 的 `300502` 弱结构样本，同时不误伤 `300394` preserve 样本；但由于 `weak_structure_triplet` 属于 window-verified selective rule，而 `volume_only_20260326` 只是 single-day hypothesis，因此当前最应优先保留的是 selective weak-structure candidate-entry 语义，而不是继续做 broad score rebalance。并且这条规则在 replay calibration 里已经有可复用的结构变体实现：`exclude_watchlist_avoid_weak_structure_entries`。

接着往前推进的关键不是直接改默认，而是先验证它到底是不是“单窗偶然”。`data/reports/btst_candidate_entry_window_scan_20260330.md` 已对当前可发现的 14 份 `paper_trading_window` 报告做了统一扫描：共有 3 份报告触发了弱结构过滤，且三者都只是同一个 `window_key=20260323_20260326` 上的重复命中；`300394` 在全部扫描结果里仍保持 `preserve_misfire_report_count=0`。这说明当前证据已经足以支持 shadow candidate-entry 旁路，但还不足以支持默认升级。

因此最新治理收口已经落在 `data/reports/p9_candidate_entry_rollout_governance_20260330.md`：`candidate_entry_rule=weak_structure_triplet`，`recommended_structural_variant=exclude_watchlist_avoid_weak_structure_entries`，`lane_status=shadow_only_until_second_window`，`default_upgrade_status=blocked_by_single_window_candidate_entry_signal`。也就是说，下一步该做的是继续累积第二个独立 `window_key` 命中，同时确保 `300394` 这类 preserve 样本持续不被误伤，而不是把 `semantic_pair_300502`、`volume_only_20260326` 或弱结构规则本身提前写成默认 admission 改动。

### 3.5 profitability 为什么值得单独提出

基于 2026-03-23、24、25、26 四个交易日（对应 `paper_trading_window` 的 `trade_dates`）的 `analyze_profitability_subfactor_breakdown.py` 分析结果（`data/reports/profitability_subfactor_breakdown_current_window_20260327.json`），需要先明确证据边界：这份统计针对 `build_candidate_pool -> score_batch -> fuse_batch` 之后、落在 `FAST_AGENT_SCORE_THRESHOLD` 下方且完成了 profitability 评分的更广义 Layer B 融合低分样本，不是 BTST-only 候选统计。

1. 有 264 个融合得分非正（`fund_nonpositive`）且实际完成了 profitability 评分的样本。
2. 其中 `net_margin` 失败 256 次，`return_on_equity` 失败 242 次，`operating_margin` 失败 242 次。
3. 有 220 个样本是三项同时失败，而且集中在电子（44）、电力设备（26）、有色金属（26）、通信（24）、机械设备（22）、国防军工（19）等与 BTST 当前活跃方向显著重叠的行业。
4. `positive_count=0` 的三项全败样本全部落入同一失败组合（`net_margin+operating_margin+return_on_equity`），说明 profitability 在这批广义低分样本里的抑制非常强。

这并不等于 profitability 没用，也不等于所有 BTST 样本都被它误杀。更准确的含义是：在这批与 BTST 活跃行业显著重叠的广义低分样本里，profitability 很可能是重要抑制源，因此它更像慢变量风险项，不适合直接照搬为 BTST 的前置硬杀器。

---

## 4. 原理分析：为什么这不是一个“多放几只票”这么简单的问题

### 4.1 BTST 本质上是一个四层问题，不是单层打分问题

当前 BTST 至少包含四层：

```text
Layer 1：机会供给
  Layer B / 候选池里，有没有足够多看起来像次日短线机会的样本。

Layer 2：边界准入
  short_trade_boundary 是否允许这些样本进入正式比较池。

Layer 3：目标评分
  short_trade_target 是否把它们判成 selected、near_miss、blocked 或 rejected。

Layer 4：执行确认
  次日盘中确认是否成立，最终是否进入 buy order，并在 T+2 退出后实现收益。
```

因此，任何只看单层结论的优化都会失真：

1. 只看 selected 数量，会忽略边界漏票。
2. 只看次日收益，会把执行问题误判成选股问题。
3. 只看 score frontier，会掩盖上游供给不足。

### 4.2 为什么“是否盈利”不足以评价 BTST 因子

如果仅用“次日买入、再下一交易日卖出是否盈利”作为评价标准，会混淆四类问题：

1. 这只票有没有给到可执行的突破机会。
2. 它是否在错误时点入场。
3. 它是否适合隔夜，而不适合开盘追价。
4. 它是否属于观察票，而不是主入场票。

更合理的 BTST 评价应分成 3 组：

1. 机会质量：T+1 是否给出足够的 intraday 空间，例如 `next_high_return`、`high_hit_rate@2%`。
2. 执行质量：若按突破确认入场，开盘到收盘、确认后到收盘、T+2 代理退出结果是否合理。
3. 风险质量：开盘反向、盘中回撤、行业集中度、样本重复性是否可接受。

### 4.3 为什么当前重点应该是修 coverage，而不是继续压质量

现在最危险的误判是：看到 `300757` 很强，就以为系统已经很准，只需要再保守一点。

但现有证据告诉我们：

1. 高质量池只有 2 个样本，统计意义太弱。
2. 旧池子里存在不少被漏掉但次日仍给空间的 false negative。
3. 如果不先恢复 coverage，后续无论做 penalty、结构冲突还是执行桥接，都只能在过小样本上打转。

所以 0330 之后的首要目标应分成两个时间层次：

1. 在历史诊断层面，要承认先前的首要问题确实是恢复 coverage 并摆脱 shared Layer B 池。
2. 在当前 live 默认路径层面，要承认这一步已经基本完成，接下来的主线应转向 `short_trade_boundary` score frontier、局部 recurring baseline 与 `layer_c_bearish_conflict` 的定点治理。

### 4.4 为什么盘中 breakout confirmation 必须单独建模

当前引擎文档已经说明：

1. T+1 confirmation 在语义上存在。
2. 但 backtesting / paper trading 里当前使用的是简化确认输入，而不是完整分钟级盘中回放。

这意味着：

1. 当前系统能告诉我们哪些票“值得次日盯突破”。
2. 但它还不能完全精确回答“几点买、在什么价位确认、买后盘中回撤多大”。

因此，0330 这轮优化路线必须把“选股优化”和“执行确认增强”拆开推进。

### 4.5 为什么 profitability 在 BTST 下应转成软约束

在中周期或研究型目标里，profitability 作为底层质量约束通常是合理的。

但在 BTST 场景里：

1. 很多高弹性行业天然会在利润率、ROE、经营利润率上吃亏。
2. 它们却可能具备强 breakout、强催化和强板块共振。
3. 如果 profitability 直接前置硬杀，会把大量“短线有效但财务不优”的机会提前清空。

因此，BTST 模式下更合理的做法是：

1. 保留 profitability 作为风险提示。
2. 在行业、催化、结构空间足够强时，将其从 hard cliff 转成 soft penalty 或 conditional penalty。

### 4.6 为什么 false negative 挖掘比继续盯 selected 更重要

本文里 false negative 的操作性定义统一为：在当前规则下被判为 `rejected`、`blocked` 或仅保留为观察层样本，但至少满足以下之一：

1. T+1 `next_high_return` 达到研究组设定的 intraday 空间门槛。
2. T+1 `close` 为正，且延续性没有明显塌陷。
3. 同类 frontier / 冲突 / 入口语义在滚动窗口中反复出现。

当前 selected 样本太少，单独研究它们会有两个问题：

1. 容易过拟合 winner 特征。
2. 无法回答“系统到底漏掉了什么”。

更有杠杆的做法是研究 false negative：

1. 被拒绝，但 T+1 `high` 很强。
2. 被拒绝，但 T+1 `close` 为正。
3. 被拒绝，但 repeated frontier 反复出现。

这些样本才是挖新因子的主矿区。

---

## 5. 方案设计：把 BTST 优化拆成 5 条并行但可控的工作流

### 5.1 总目标

0330 之后的 BTST 优化总目标应统一为一句话：

> 在不破坏 `short_trade_boundary` 当前质量优势的前提下，恢复可研究的 coverage，并把“值得盯盘的票”和“值得执行的票”明确分层。

### 5.2 五条工作流

| 工作流 | 核心问题 | 主要抓手 | 首轮成功标准 |
| --- | --- | --- | --- |
| A. Coverage 修复 | 当前值得研究的票是否太少 | `breakout_freshness` 语义、candidate entry 边界、boundary admission | 候选数回升，但 `next_high_hit_rate` 不明显恶化 |
| B. Quality 守门 | 新增样本是否只是噪声 | `next_high_return`、`next_close_return`、行业集中度、重复票比例 | 扩覆盖后仍保持可接受的 hit rate |
| C. 执行确认分层 | 会选和会买如何拆开 | `selected` / `near_miss` / watch-only 结构、盘中确认代理 | 主入场票与观察票的语义更稳定 |
| D. 慢变量软化 | fundamental 是否压制过强 | profitability 软惩罚、行业条件豁免 | false negative 数下降，质量不明显塌陷 |
| E. 新因子挖掘 | 现有字段解释不了哪些机会 | intraday confirmation、开盘消化、板块共振、结构空间 | 出现可重复解释的新分型或新特征 |

### 5.3 统一验证框架：每轮实验都要看 5 组指标

| 指标组 | 代表字段 | 用来回答什么 |
| --- | --- | --- |
| Coverage 指标 | `candidate_count`、`selected_count`、`near_miss_count` | 这轮实验有没有把样本池打开 |
| Opportunity 指标 | `next_high_return_mean`、`high_hit_rate@2%` | 这些票是否至少给过次日空间 |
| Execution 指标 | `next_open_return`、`next_open_to_close_return`、确认后收益 | 如果不追开盘，执行后是否更合理 |
| Stability 指标 | 行业分布、重复 ticker、日间波动 | 结果是否稳定，是否只是在赌单一主题 |
| Learnability 指标 | false negative archetype、失败簇迁移 | 这轮实验有没有帮助我们学到新东西 |

这 5 组指标里，Coverage 不是唯一目标，Opportunity 才是 BTST 最核心的上位指标。

---

## 6. 微窗口设计：把你提出的方法改造成可复用研究模板

### 6.1 当前微窗口应该如何定义

严格来说，当前讨论窗口不是“三天”，而是 4 个收盘日：

1. 2026-03-24 收盘选股，2026-03-25 观察或入场，2026-03-26 退出。
2. 2026-03-25 收盘选股，2026-03-26 观察或入场，2026-03-27 退出。
3. 2026-03-26 收盘选股，2026-03-27 观察或入场，2026-03-30 退出。
4. 2026-03-27 收盘选股，2026-03-30 观察或入场，2026-03-31 退出。

> **日期口径对照**：paper trading 引擎里的 `trade_date` 是分析执行日（即选股当天），对应上表每行的"收盘选股"列。因此 `paper_trading_window` 的 `trade_dates = [20260323, 20260324, 20260325, 20260326]` 对应的收盘选股日分别是 2026-03-23、24、25、26。Section 3.2–3.5 引用的 blocker / pre-Layer C / profitability 报告均以 `trade_date` 口径标注日期，而本节以"收盘选股日"口径。两者差异仅是术语不同，实际指向同一组交易日。

其中第 4 组在 2026-03-30 当下还没有完整 T+2 结果，因此本轮可分为：

1. 完整样本：`20260324`、`20260325`、`20260326`。
2. 半完整样本：`20260327`，目前只能评价 T+1 的执行准备度和盘中关注等级。

### 6.2 微窗口里不建议只看一种收益口径

还要额外强调一条边界：`T+2 close` 在当前阶段只是 post-hoc 结果代理，用来辅助评价隔夜 continuation，不应被误读为系统已经具备分钟级真实可执行 BTST PnL 还原。

建议最少同时保留 4 条评价线：

1. `T+1 open`：如果直接开盘买，会不会追得太差。
2. `T+1 high`：如果等盘中确认，这只票有没有给过你执行空间。
3. `T+1 close`：这只票的次日延续性是否成立。
4. `T+2 close`：如果按 BTST 口径隔夜到下一交易日退出，整体结果是否仍成立。

这能把“机会存在但执行点不同”和“机会本身就不存在”区分开。

### 6.3 微窗口的标准输出应是什么

建议每个 trade_date 最少产出 4 类结果表：

1. 主入场票表：`selected` 且适合次日盘中确认后执行。
2. 观察票表：`near_miss` 或 watch-only，不默认买入，但需要跟踪。
3. false negative 表：被拒绝，但次日 `high` 或 `close` 表现仍然强。
4. blocker 迁移表：这轮实验后，失败簇从哪一层迁移到了哪一层。

这样研究团队不会只盯着“买没买”，而能同时判断“系统有没有漏好票”。

### 6.4 2026-03-30 夜间已经补出的微窗口实证结果

截至 2026-03-30 夜间，`2026-03-23` 到 `2026-03-26` 的 closed-cycle 微窗口回归已经被正式固化为报告：[btst_micro_window_regression_20260330.md](../../../../../data/reports/btst_micro_window_regression_20260330.md)。这份报告把 baseline、`catalyst_floor_zero` 变体和 `2026-03-27` 的 forward-only short-trade 样本放进了同一套口径里比较。

它给出的结论非常关键：

1. baseline 在 `2026-03-23` 到 `2026-03-26` 的 closed-cycle 样本里一共 32 行，但 `tradeable surface=0`，说明旧 baseline 在这个闭环窗口里并没有形成可执行 short-trade surface。
2. 同一窗口下 baseline 仍有 19 个 false negative proxy，且主要来自 `layer_b_boundary`；它们的 `next_high_hit_rate@2%=0.7895`、`next_close_positive_rate=0.8421`，说明问题不是“市场没给机会”，而是系统漏掉了不少机会。
3. `catalyst_floor_zero` 变体把 closed-cycle actionable 样本从 `0` 提升到 `6`，并给出 `next_high_hit_rate@2%=0.8333`、`next_close_positive_rate=0.8333`、`t_plus_2_close_positive_rate=0.8333`，正式通过当前窗口的 closed-cycle guardrail。
4. `2026-03-27` 的 short-trade-only 样本虽然已经出现 2 个可研究 tradeable 行，但它们都还是 `t1_only`，因此只能算 forward 观察证据，不能直接当成默认升级依据。

这意味着：在 0330 当前证据边界内，微窗口方法本身已经完成验证，下一步主线不应再回到“是否继续大范围 admission floor 扫描”，而应固定为三件事：

1. 保留 `short_trade_boundary + catalyst_freshness_min=0.00` 作为当前 live admission 基线。
2. 继续围绕 `short_trade_boundary_score_fail`、`001309/300383` 与 `300724` 的结构性治理推进 score frontier、selective candidate-entry rule 与 case-based lane。
3. 等未来新增独立窗口出现后，再用同一份微窗口回归脚本继续验证 `001309` primary lane 和 recurring shadow lane 的跨窗口稳定性。

---

## 7. 因子优化方向：下一轮最值得做的不是一锅炖，而是 4 个最小主线

本节覆盖 Section 5.2 五条工作流中的 A（Coverage 修复）、B（Quality 守门）、C（执行确认分层）、D（慢变量软化），工作流 E（新因子挖掘）见 Section 8。对应执行清单的 P2–P5 优先级。

### 7.1 主线一：重做 breakout freshness 的使用方式，而不是继续阈值扫描

现有证据显示，大量样本反复卡在 `breakout_freshness`。

建议优先回答两个问题：

1. 当前 `breakout_freshness` 是否过度偏好“已经非常像强突破完成态”的样本。
2. 它是否错杀了“收盘已进入突破准备态，但确认要到次日盘中完成”的样本。

可行的改造方向：

1. 把 `breakout_freshness` 从单一 admission floor，改成 admission + score 两段式影响。
2. 引入“准备突破态”和“完成突破态”分层，而不是只允许后者进入。
3. 允许一部分 `near_miss` 级别样本进入 watch-only 池，而不是直接拒绝。

其中第 2 条现在已经有了最小代码原型：`staged_breakout` profile 会把 `near_miss` 解释成“prepared_breakout”，但最新 closed-cycle frontier 结果也同时说明，仅靠这层 profile 语义仍不足以把当前窗口推出 actionable surface，因此它更适合保留为实验语义，而不是当前默认主线。

### 7.2 主线二：把 profitability 从前置硬杀改成 BTST 软约束

这一主线不是让 fundamental 失效，而是让它在 BTST 模式下从“硬闸门”变成“风险权重”。

建议分三步做：

1. 先在微窗口里统计 profitability 全败但次日仍给空间的样本比例。
2. 再做条件式软化，只对高 breakout、高催化、板块强共振行业放松。
3. 最后比较软化前后 false negative 是否显著下降。

不建议一开始就全局取消 profitability。

### 7.3 主线三：把主入场票和观察票做成显式双名单

这次 `300757 / 601869` 的分层已经在 brief / review 层提供了正确方向：

1. `selected` 对应主入场票，要求次日盘中确认后才考虑执行。
2. `near_miss` 对应观察票，只做盘中跟踪，不默认转买入。

下一步应把这套双名单机制扩展成稳定规则，并明确区分 report-layer semantics 与 execution-layer contract，而不是继续依赖临时人工解释。

这比简单把 near-miss 全部抬成 selected 更安全，也更贴合实际交易决策。

### 7.4 主线四：优先挖 false negative archetype，而不是追 single winner story

下一轮研究不应只盯 `300757` 这种成功案例，而应重点提炼三类 false negative：

1. `score fail but high works`：分数没过，但次日高点表现明显成立。
2. `watch-only but tradable intraday`：更适合观察票语义，而不是主入场票。
3. `structural conflict but pattern recurs`：同一种冲突样本反复在同类行业出现。

这些 archetype 才能支撑后续新因子设计。

---

## 8. 新因子挖掘方向：优先从 6 类“现有规则没说清楚”的信息里找

### 8.1 开盘消化能力

要回答的问题：

1. 次日开盘是否跳得过高，导致不适合开盘追价。
2. 即使不适合追开盘，盘中是否仍然给出更好的确认点。

首轮验证口径：

1. `next_open_return`
2. `next_open_to_close_return`
3. `next_high_return - next_open_return`

### 8.2 盘中确认质量

要回答的问题：

1. 这只票是否在次日真正形成了“突破后站住”的结构。
2. 它是高开即兑现，还是盘中二次确认后走强。

首轮验证口径：

1. 先用现有 T+1 confirmation proxy 做弱验证。
2. 后续升级到分钟级数据时，再做真实 breakout confirmation quality 因子。

### 8.3 结构空间因子

现有 penalty 已经在表达这件事，但还不够显式。

建议把下列信息独立成可读字段：

1. extension 是否过大。
2. overhead 是否过重。
3. 剩余上行空间是否足够支持 BTST。

这类因子适合解释“为什么有催化、有趋势，但仍然不该追”。

### 8.4 板块共振与领涨密度

当前很多 BTST 机会并不是单票事件，而是板块短期共振。

建议挖掘：

1. 同行业当天是否同时出现多个高强度样本。
2. 龙头票是否具备更强的次日 follow-through。
3. profitability 全败但板块共振极强时，是否应给予条件豁免。

### 8.5 催化剂兑现节奏

现在 `catalyst_freshness` 只描述“是否新”，但未充分描述“是否正在兑现”。

建议扩展成两类判断：

1. 新催化但尚未扩散。
2. 新催化且已经开始被市场快速兑现。

这将直接影响主入场票和观察票的划分。

### 8.6 行业条件化 profitability 豁免

不是所有行业都该用同一套 profitability 压制逻辑。

建议把豁免研究限定在：

1. 电子
2. 通信
3. 机械设备
4. 国防军工
5. 有色金属
6. 电力设备

理由不是这些行业天然更好，而是它们在当前窗口里同时满足：

1. profitability 压制强。
2. BTST 活跃度高。
3. 更可能产出“财务不优但短线有效”的样本。

---

## 9. 执行计划路线：建议按 5 个阶段推进，而不是一次性大改

### 9.1 Phase 0：冻结 baseline，先形成研究底稿

目标：让所有后续实验都有可追溯参照。

动作：

1. 固定当前 baseline 输出目录、样本窗口、目标模式和模型版本。
2. 整理 2026-03-24 到 2026-03-27 的 trade_date 级样本表。
3. 明确 `selected / near_miss / blocked / rejected / false negative` 五类标签口径。

产物：

1. 微窗口样本总表。
2. 当前 baseline 指标页。
3. 研究员评审问题单。

### 9.2 Phase 1：先做微窗口双层验证，不先改规则

目标：回答“当前系统漏掉的到底是什么样的票”。

动作：

1. 对 2026-03-24、25、26 的完整样本，分别计算 T+1 机会指标和 T+2 出场指标。
2. 对 2026-03-27 的半完整样本，只先看 T+1 盘中关注等级。
3. 形成主入场票、观察票、false negative 三张表。

产物：

1. 微窗口 workbook。
2. false negative dossier 初版。
3. 主入场票 / 观察票分层说明。

### 9.3 Phase 2：只做单主题变体，不做组合拳

目标：用最低实验成本定位最有杠杆的改动点。

推荐顺序：

1. `short_trade_boundary` score frontier 的单主题 release / promotion 变体。
2. profitability 软惩罚小变体。
3. watch-only 双名单扩展。
4. 结构冲突 case-based release。

这里需要明确一条与上游实施文档一致的阶段边界：`catalyst_freshness_min=0.00` 已经完成完整窗口 live 验证，旧 shared `layer_b_boundary` 失败簇也已经被 dedicated builder 清零，因此 Phase 2 不应重新退回到 admission floor 大范围网格扫描；除非未来新窗口出现新的 admission 失败簇，否则当前默认单主题变体应以 score frontier 为起点；若 score-only 变体仍然维持 `0 actionable`，就应转入 selective candidate-entry frontier，而不是回退到 broad admission 扫描。

纪律：

1. 一轮只动一类机制。
2. 每轮都同时产出 Coverage、Opportunity、Stability 三组指标。
3. 若结果只能提升通过数、不能提升学习价值，则不进入下一轮。

### 9.3.1 Phase 2 的临时进退门槛

下表不是生产默认阈值，而是 0330 微窗口研究阶段的临时 gate，用来避免“放了票但机会质量明显塌陷”仍被误判为成功。

| 状态 | 触发条件 | 处置 |
| --- | --- | --- |
| Go | 新增样本 `> 0`，且 `next_high_hit_rate@2%` 不低于旧 `layer_b_boundary` 基线 `0.5217`，`next_close_positive_rate` 不低于旧基线 `0.5652`，同时没有出现单一 ticker 或单一行业主导全部新增样本 | 允许进入下一主题或滚动窗口复核 |
| Shadow only | 新增样本 `> 0`，但只满足一项机会指标，或样本明显集中在单一风格 / 单一行业 | 只保留为影子变体，不讨论默认升级 |
| Rollback | `next_high_hit_rate@2%` 与 `next_close_positive_rate` 同时跌破旧 `layer_b_boundary` 基线，或新增样本没有产生任何可解释的 false negative archetype | 终止该变体，不进入下一轮 |

### 9.4 Phase 3：扩到滚动窗口，再谈默认升级

目标：避免在 4 日小窗上过拟合。

结合 2026-03-30 夜间 Top 3 真实执行结果，Phase 3 的默认起点不再是“任意最佳单主题变体”，而应明确限定为 `001309_primary_controlled_follow_through`。`300383` 只作为 shadow queue 旁路参考保留，`300724` 则只保留为 structural shadow hold，不进入默认升级候选池。

动作：

1. 把最佳单主题变体扩到更长滚动窗口。
2. 比较 baseline 与变体在 hit rate、close 胜率、行业分布、重复 ticker 上的差异。
3. 检查新增样本是否主要来自单一行情风格。

在当前收口口径下，还应额外执行两条治理约束：

1. `001309` 只有在新增独立窗口后仍保持 `changed_non_target_case_count=0`、`next_close_return_mean>0`、`next_close_positive_rate>=0.75`，才允许进入默认升级评审。
2. `300383` 即使继续保留为 shadow，也只能作为单票 threshold-only release；如果要扩大 shadow lane，应优先转向 recurring frontier lane，而不是复制它的同一套阈值放松规则。
3. recurring frontier lane 内部也要继续分层：`002015` 作为 close-continuation shadow 候选优先推进，`600821` 只作为 intraday control 保留，防止 shadow 扩展再次把 intraday upside 误当成可默认升级的 close 规则。
4. 截至 2026-03-30，Phase 3 的方法闭环已经补齐：新增窗口扫描、证据缺口说明、roll-forward 判定、治理板回接都已具备；当前唯一无法在本轮直接“完成”的部分，是新增独立窗口尚未自然出现。

只有在滚动窗口稳定后，才允许进入默认升级讨论。

### 9.4.1 Phase 3 的默认升级门槛

1. 如果变体在滚动窗口里只能偶发释放单一 ticker，或只在单一风格窗口有效，则继续保留为 case-based / shadow 变体。
2. 如果变体在滚动窗口里新增样本持续存在，且机会指标没有重新跌回旧 `layer_b_boundary` 基线以下，才允许进入默认升级讨论。
3. 只要滚动窗口再次出现新的大失败簇，或新增样本主要转化成低质量噪声，就应回退到 Phase 2，重新拆机制定位，而不是继续叠加改动。

### 9.5 Phase 4：执行确认增强

截至 2026-03-30，Phase 4 的执行前置件也已经补齐到当前证据边界：主入场票 / shadow / recurring shadow / intraday control 的 lane 已全部分开，且各自都有 stop condition、治理板和 runbook。后续真正新增的工作量，主要来自新窗口执行数据与更细粒度 execution confirmation 数据，而不是 0330 这份路线仍有定义缺口。

目标：把“会选”与“会买”之间的缺口单独补齐。

动作：

1. 把当前 confirmation proxy 的局限显式写入研究结论。
2. 设计分钟级或更细粒度的 intraday confirmation 研究方案。
3. 明确哪些因子只能在 execution 层验证，而不能继续让 selection 层背锅。

这一步不应和 coverage 修复绑在一轮里一起做。

---

## 10. 评审与验收口径：研究员审这份路线时应重点问什么

评审时建议重点问下面 10 个问题：

1. 这条路线是否明确区分了 coverage、quality 和 execution 三个层级。
2. 它是否承认 `300757` 是主入场票，但并未把它误写成开盘追价票。
3. 它是否承认 `601869` 是观察票，而不是被误提升成默认买入票。
4. 它是否避免把 `blocked` 与 `rejected` 混在一起调。
5. 它是否给出了微窗口与滚动窗口两层验证，而不是停留在单窗口结论。
6. 它是否把 profitability 的角色从“取消”改成“条件化软化”。
7. 它是否明确要求先做 false negative 挖掘，再做新因子定义。
8. 它是否规定每轮只允许一个实验主题，避免归因失效。
9. 它是否承认当前 execution confirmation 仍是 proxy，不夸大回测可信度。
10. 它是否包含停止条件，而不是默认所有实验都继续做下去。

---

## 11. 明确禁止的动作

在 0330 之后的优化中，下面这些动作应明确禁止：

1. 只因为 `selected` 太少，就直接整体下调 `select_threshold`。
2. 只因为 `near_miss` 看起来不错，就把 near-miss 全部抬升成默认买入。
3. 在 4 日小窗口里同时修改 admission、penalty、profitability 和 execution。
4. 用“最终是否赚钱”替代 BTST 的分层验证。
5. 在没有更长滚动窗口验证前，讨论默认升级。

---

## 12. 一句话总结

0330 这轮 BTST 讨论的正确落点，不是证明市场上只有 `300757` 一只票，而是确认当前系统把大量潜在机会挡在了 coverage 与边界语义之前。下一步最有杠杆的路线，是先用微窗口双层验证把 false negative 挖出来，再围绕 `breakout_freshness`、profitability 软化、主入场票 / 观察票双名单和 execution confirmation 分层，做单主题、可归因、可滚动验证的优化闭环。
