# 0330 BTST 可交易涨幅池与漏票召回方案

文档日期：2026 年 4 月 2 日  
适用对象：需要从 2026 年 3 月历史窗口出发，系统性提升 BTST 选股覆盖、胜率、盈亏比与研究治理质量的研究员、策略负责人、开发者、AI 助手。  
文档定位：把“3 月每天强票很多，但系统放行太少”的直觉，收敛成一套可直接实施的专项方案。它不直接把“涨停股都留下来”当成目标，而是先建立全市场结果真值池，再收缩成可交易机会池，最后提升系统对这些机会的召回率与排序质量。

建议搭配阅读：

1. [0330 优化路线设计文](./README.md)
2. [0330 BTST 研究执行清单](./01-0330-research-execution-checklist.md)
3. [0330 BTST 3 月最小回测方案](./02-0330-march-btst-minimal-backtest-plan.md)
4. [BTST 微窗口回归摘要](../../../../../data/reports/btst_micro_window_regression_20260330.md)
5. [BTST T+1 / T+2 目标监控](../../../../../data/reports/btst_tplus1_tplus2_objective_monitor_latest.md)
6. [baseline 短线阻断分析](../../../../../data/reports/short_trade_blocker_analysis_baseline_full_20260329.md)
7. [layer_b_boundary 过滤候选复盘](../../../../../data/reports/short_trade_boundary_filtered_candidates_current_window_20260329.md)

---

## 1. 先讲结论

你的思路是对的，但必须升级成“可交易涨幅池”方案，而不是“所有涨停 / 所有大涨股回捞方案”。

当前 BTST 的问题，不是市场没有机会，而是系统对短线机会的召回率过低、分层不够清晰、执行语义和研究语义仍然部分混杂。

现有证据已经足够支持这一判断：

1. baseline 在 `2026-03-23` 到 `2026-03-26` 的 closed-cycle 窗口里 `tradeable surface=0`，但同一窗口有 19 个 false negative proxy，说明机会存在、系统漏了很多。
2. 这 19 个 false negative proxy 的 `next_high_hit_rate@2%=0.7895`、`next_close_positive_rate=0.8421`，质量显著高于“当前系统根本没有机会”的假设。
3. 目标监控里当前 `tradeable_surface` 的 `T+2 positive_rate=0.7143`，但 `T+2 >= 5%` 的命中率只有 `0.2857`，说明系统距离“80% 概率赚钱且赚 5% 以上”的目标还很远，不能靠简单多放几只票解决。
4. 现有主失败簇并不是“完全没信号”，而是边界准入与评分链路过冷。baseline 报告里最大的失败簇是 `rejected_layer_b_boundary_score_fail=23`；而当前更活跃的真实前沿已经转向 `short_trade_boundary_score_fail`、局部 candidate entry 语义和定点 structural block 治理。

因此，这轮专项的正确目标应该拆成两段：

1. 先把全市场里真正给过短线空间、且事后看起来具有可交易性的票找出来，建立“可交易机会池”。
2. 再分析系统到底在哪一层把这些票过滤掉，并优先修复最大、最稳定、最可控的失败簇。

这套方案的核心不是“先把所有强票都留下来”，而是：

1. 先提高对可交易机会的召回率。
2. 再在已召回的样本里提高排序和执行质量。
3. 最后才讨论如何把主执行池逼近 `80%` 胜率与 `5%` 收益目标。

---

## 2. 当前现状到底出了什么问题

### 2.1 市场机会很多，但系统放行太少

基于 [BTST 微窗口回归摘要](../../../../../data/reports/btst_micro_window_regression_20260330.md)：

1. baseline 在 `2026-03-23` 到 `2026-03-26` 的验证窗口中，`selected=0`、`near_miss=0`、`blocked=5`、`rejected=27`。
2. 同一窗口里 `tradeable surface=0`，这意味着系统最终没有形成任何可研究的主执行面。
3. 但 baseline 同时存在 19 个 false negative proxy，且这些样本的后验质量并不差。
4. 这说明系统当前的主要矛盾不是“市场里没有短线票”，而是“系统没把足够多的可交易票保留下来”。

### 2.2 当前最明显的错杀链路是边界供给与评分前沿

基于 [baseline 短线阻断分析](../../../../../data/reports/short_trade_blocker_analysis_baseline_full_20260329.md)：

1. 32 个 short-trade 样本里，最大的失败簇是 `rejected_layer_b_boundary_score_fail=23`。
2. 这 23 个样本都来自 `layer_b_boundary`，说明旧路径下共享边界供给和 short-trade 评分之间存在明显断层。
3. 另一个重要失败簇是 `blocked_structural_bearish_conflict=5`，说明结构冲突不是主矛盾，但也不是可以忽略的噪声。

基于 [layer_b_boundary 过滤候选复盘](../../../../../data/reports/short_trade_boundary_filtered_candidates_current_window_20260329.md)：

1. 23 个 `layer_b_boundary` 候选里，没有一个通过当前短线边界 floor。
2. 其中 19 个主要卡在 `breakout_freshness_below_short_trade_boundary_floor`。
3. 这说明当前 admission 主问题不是“阈值微调一下就好”，而是 breakout / short-trade readiness 语义定义过窄。

### 2.3 当前系统并没有达到严格 BTST 目标

基于 [BTST T+1 / T+2 目标监控](../../../../../data/reports/btst_tplus1_tplus2_objective_monitor_latest.md)：

1. 当前 `tradeable_surface` 的 `T+2 positive_rate=0.7143`，仍低于 `0.8`。
2. 当前 `tradeable_surface` 的 `T+2 >= 5%` 命中率只有 `0.2857`，离目标差距更大。
3. 最接近严格目标的不是“整个 BTST 总池”，而是少数高度集中的 ticker / lane。

这意味着：

1. `80%` 胜率与 `5%` 收益命中率可以作为目标。
2. 但它只能先在更窄、更高确定性的主执行池里追求，而不是一开始就拿全部 BTST 候选池要求达成。

### 2.4 为什么“把所有涨停股都留下来”不是正确目标

当前候选池在 [src/screening/candidate_pool.py](../../../../../src/screening/candidate_pool.py) 里会直接排除“当日涨停”标的，这是合理的。

原因很直接：

1. A 股很多最猛的票在收盘前已经没有可买性。
2. 很多一字板、秒板、封单过重的票，事后很强，但对“收盘选股、次日买入”的 BTST 语义并不友好。
3. 如果把这些票无差别纳入目标池，系统会学到大量“看起来对、实盘根本买不到”的伪 edge。

因此，用户提出的“涨幅池”必须升级成“可交易涨幅池”。

---

## 3. 本方案的核心框架：四池两阶段一条红线

### 3.1 四池框架

为了同时解决“漏票”和“过拟合”，本方案把研究对象拆成四层。

| 层级 | 名称 | 定义 | 用途 |
| --- | --- | --- | --- |
| Pool A | 结果真值池 | 全市场中，T+1 或 T+2 事后表现显著强的样本 | 回答“市场里到底有没有机会” |
| Pool B | 可交易机会池 | 在结果真值池上再施加可买性、流动性、交易摩擦约束后的样本 | 回答“哪些机会理论上值得被 BTST 看见” |
| Pool C | 系统召回池 | 当前系统中进入候选、边界、near-miss、selected 的样本 | 回答“系统到底看见了多少机会” |
| Pool D | 主执行池 | selected + 通过明确执行 contract 的高确定性 near-miss 样本 | 回答“最终真正拿去交易的应该是谁” |

这四池的关系不能混淆：

1. Pool A 用来做结果真值，不直接拿来改默认值。
2. Pool B 是本轮专项的主目标池，决定我们要优先救哪些漏票。
3. Pool C 用来做归因，判断系统漏在什么地方。
4. Pool D 才是未来要追求 `80%` 胜率与 `5%` 收益目标的窄池。

### 3.2 两阶段优化

本方案强制把优化拆成两阶段。

第一阶段是“召回”。

1. 优先提升 Pool B 到 Pool C 的覆盖率。
2. 核心问题是：可交易机会有没有被系统感知、保留、标注成 near-miss 或 selected。

第二阶段是“排序与执行”。

1. 在已召回的样本中，进一步筛出真正值得次日买入、后天卖出的窄池。
2. 核心问题是：这些样本中谁更适合做主入场票，谁只能做观察票，谁虽然是 false negative 但不应实盘追。

### 3.3 一条红线

本方案有一条红线：

1. 不允许为了提升召回率，把明显不可交易的涨停 / 一字板 / 极端高开票直接当成“必须放行样本”。

也就是说：

1. 我们追的是“可交易机会召回”，不是“事后最强票召回”。
2. 这也是 A 股超短线里最重要的风控边界之一。

---

## 4. 业界最佳做法是什么

对于 A 股超短线、BTST、隔夜延续类系统，业界更稳的方法通常不是“直接找收益最高的票”，而是下面这套顺序：

1. 先建立全市场结果真值池，避免把系统当前看到的世界误当成真实世界。
2. 再施加交易可达性约束，形成 tradeable opportunity universe。
3. 然后拆成召回模型和排序模型，而不是让单一分数同时负责“看见机会”和“决定买谁”。
4. 最后把执行 contract 单独治理，区分主入场票、观察票、盘中确认票、禁止追价票。

对于当前仓库，最接近业界最佳实践、也最快能落地的路径是：

1. 继续复用现有 `false_negative`、`near_miss`、`blocked` 诊断链路。
2. 新增一层“从全市场结果真值池回看 BTST 漏票”的外部视角分析。
3. 用这个外部视角去驱动 `score frontier`、`candidate entry`、`targeted structural release` 三条现有主线，而不是重开大范围 admission 扫描。

---

## 5. 我们要建立的不是“涨停池”，而是“可交易机会池”

### 5.1 Pool A：结果真值池的定义

结果真值池用于回答“市场里哪些票在 BTST 持有语义下，事后表现真的强”。

建议初始使用三档标签：

1. `intraday_strong`：`next_high_return >= 0.05`。
2. `close_continuation_strong`：`next_close_return >= 0.03`。
3. `strict_btst_goal_case`：`t_plus_2_close_return >= 0.05`。

解释：

1. 第一档回答“次日盘中有没有给到足够空间”。
2. 第二档回答“次日收盘有没有形成确认延续”。
3. 第三档回答“如果按 BTST 持有到 T+2，是否达到你的严格目标”。

### 5.2 Pool B：可交易机会池的定义

结果真值池不能直接拿来优化系统，必须加交易约束。

第一版建议保留以下约束：

1. 非 ST。
2. 非北交所。
3. 非新股。
4. T 日未停牌。
5. T 日未涨停封死。
6. T+1 至少存在可计算的 open / high / close。
7. 剔除明显不可复制的一字板或极端不可追价样本。
8. 剔除成交额明显不足、冲击成本过高样本。

这里必须承认一个现实边界：

1. 当前仓库多数分析使用日线与回放产物，不是分钟级撮合回放。
2. 因此“是否真的可买到”只能先做近似判断，而不能假装已经还原实盘成交。

所以第一版可交易机会池应理解为：

1. “高概率具备交易可达性”的回顾性机会池。
2. 不是“已经精确还原分时成交的实盘买入池”。

### 5.3 Pool C：系统召回池的定义

系统召回池包含：

1. 进入 `selection_snapshot` 的 short-trade 候选。
2. 进入 `candidate_source` 的边界样本。
3. 被打成 `selected`、`near_miss`、`rejected`、`blocked` 的样本。

这一层的目标不是盈利，而是做归因：

1. 系统到底有没有看到这只票。
2. 它最早死在什么地方。
3. 死掉的原因是结构性、评分型还是执行型。

### 5.4 Pool D：主执行池的定义

主执行池是未来真正要追 `80%` 胜率与 `5%` 收益命中率的对象。

它不等于所有 selected，也不等于所有 near-miss。

Pool D 应满足：

1. 当前 short-trade 评分通过或接近通过。
2. 有明确的 `preferred_entry_mode`。
3. 事后执行代理没有明显反证，例如开盘极端差、盘中确认空间不足。
4. 不属于明显的结构冻结或只应 shadow 的样本。

---

## 6. 当前最值得优先改的，不是所有地方，而是 5 个杠杆

### 6.1 杠杆一：建立全市场回看视角

当前所有诊断基本都从“系统已看到的样本”出发。

这会带来一个问题：

1. 如果系统根本没看到某只票，我们就无法知道它被漏在了哪里。

因此，第一优先级不是继续调参数，而是先建立“从全市场强票往回映射到系统”的外部真值视角。

这是本轮新增分析框架的核心。

### 6.2 杠杆二：统一“第一阻断点”归因口径

每只 Pool B 样本都必须找到一个“第一阻断点”。

建议统一用下面这套瀑布口径：

1. `universe_prefilter`：ST、北交所、新股、停牌、冷却期等基础过滤。
2. `day0_limit_up_excluded`：T 日已不可买。
3. `no_candidate_entry`：没有进入任何 short-trade 候选入口。
4. `candidate_entry_filtered`：候选入口规则直接过滤。
5. `boundary_filtered`：停在 `layer_b_boundary` 或 `short_trade_boundary`。
6. `score_fail`：进入 short-trade 评分，但没有到 near-miss。
7. `structural_block`：被 `layer_c_bearish_conflict` 或类似机制阻断。
8. `execution_contract_only`：研究上值得盯，但不应直接进主执行池。
9. `selected_or_near_miss`：系统已感知并保留。

这样做的好处是：

1. 你不再只看到“这只票被拒了”。
2. 你会知道“它最早死在什么地方”。
3. 后续优化就能按失败簇排序，而不是按印象排序。

### 6.3 杠杆三：优先修 short_trade_boundary 的分数前沿

当前证据说明，继续大范围扫描 shared admission floor 的收益已经下降。

更值得优先推进的是：

1. `short_trade_boundary_score_fail` 的前沿样本。
2. breakout / trend / catalyst / volume 这几个组成 short-trade readiness 的局部前沿。
3. 以 false negative 真实后验表现为依据，判断哪些 threshold / weight / semantic rule 值得影子释放。

### 6.4 杠杆四：profitability 必须继续保持“软约束化”方向

profitability 在 BTST 场景里更像慢变量风险，不适合直接做前置硬杀。

后续方向应是：

1. 保留 profitability 作为 penalty / 风险提示。
2. 只在 breakout、catalyst、sector resonance 明显强时做条件化软化。
3. 禁止一刀切全局取消 profitability。

### 6.5 杠杆五：结构冲突只做定点治理

结构冲突不是当前主失败簇，但它会伤到高价值样本。

因此后续只做：

1. 单票或单簇定点 release。
2. 必须同步检查 `changed_non_target_case_count`。
3. 禁止 cluster-wide 全局放松。

---

## 7. 具体要怎么改

### 7.1 第一批必须新增的分析产物

建议新增以下主产物：

1. `data/reports/btst_tradeable_opportunity_pool_march.json`
2. `data/reports/btst_tradeable_opportunity_pool_march.md`
3. `data/reports/btst_tradeable_opportunity_pool_march.csv`
4. `data/reports/btst_tradeable_opportunity_reason_waterfall_march.json`
5. `data/reports/btst_tradeable_opportunity_reason_waterfall_march.md`

这两组产物分别回答两件事：

1. 3 月到底有哪些“值得被 BTST 看到”的可交易机会。
2. 这些机会分别死在系统的哪一层。

### 7.2 第一批建议新增的脚本

建议新增脚本：

1. `scripts/analyze_btst_tradeable_opportunity_pool.py`

它的职责是：

1. 扫描给定日期区间内的全市场样本。
2. 计算每个样本的 `next_open_return`、`next_high_return`、`next_close_return`、`t_plus_2_close_return`。
3. 按结果阈值打上 `intraday_strong`、`close_continuation_strong`、`strict_btst_goal_case` 标签。
4. 按可交易规则筛出 Pool B。
5. 再将 Pool B 回映射到给定 report dir 或 reports root 下的 `selection_snapshot` / `selection_target_replay_input` / `daily_events`。
6. 为每只票输出“第一阻断点”。
7. 生成原因瀑布、行业分布、candidate_source 分布、false negative 优先级榜。

第一版为了速度，可以直接复用现有脚本里的公共逻辑：

1. 复用 `scripts/analyze_btst_micro_window_regression.py` 中的价格结果提取与 snapshot 遍历方式。
2. 复用 `scripts/analyze_btst_tplus1_tplus2_objective_monitor.py` 中的目标阈值和严格目标 case 口径。
3. 复用 `scripts/analyze_short_trade_blockers.py` 中的 blocker / gate_status / candidate_source 汇总逻辑。

### 7.3 第二批建议新增的集成点

在第一版分析脚本验证有效后，建议继续接入：

1. `scripts/run_btst_nightly_control_tower.py`
2. `scripts/generate_reports_manifest.py`
3. `data/reports/report_manifest_latest.*`

目标是让 nightly 层面固定出现以下摘要：

1. 最新窗口下 Pool B 总量。
2. Pool B 被系统召回的比例。
3. 第一阻断点 Top 3。
4. strict BTST goal case 中被错杀的 Top N。

### 7.4 第一批建议新增的测试

建议新增：

1. `tests/test_analyze_btst_tradeable_opportunity_pool_script.py`

至少覆盖：

1. 结果池标签判定正确。
2. 可交易机会池过滤逻辑正确。
3. 第一阻断点瀑布不会重复归因。
4. 缺少某些 report artifact 时，脚本仍能稳定降级输出。

---

## 8. 文档级实施路线

### Phase 0：定义冻结

目标：先把口径统一，避免后面反复争论。

必须冻结的定义：

1. 结果真值池阈值。
2. 可交易机会池阈值。
3. 第一阻断点分类。
4. Pool D 的主执行口径。

通过条件：

1. 研究侧和工程侧对四池定义没有歧义。
2. 文档里明确写出哪些票属于“可研究强票”，哪些票属于“不可交易强票”。

### Phase 1：先把 3 月 Pool B 跑出来

目标：先知道“我们到底漏了谁”。

输出：

1. 3 月全窗口 Pool A / Pool B 总表。
2. Pool B 原因瀑布。
3. 严格目标样本榜。
4. Top false negative 榜单。

通过条件：

1. Pool B 归因覆盖率达到 `100%`，每只票都有第一阻断点。
2. 至少能明确回答“3 月最大的漏票失败簇是什么”。

### Phase 2：只修最大失败簇

目标：不要同时动太多东西。

优先顺序建议固定为：

1. `short_trade_boundary_score_fail`。
2. selective candidate entry semantics。
3. profitability 条件化软化。
4. targeted structural release。

通过条件：

1. 每轮只动一个主题。
2. Pool B 的召回率上升。
3. 新增样本质量不低于当前 false negative guardrail。

### Phase 3：把高召回池进一步压缩成主执行池

目标：从“看见更多机会”，切换到“真正拿去买的更准”。

做法：

1. 把 selected、near-miss、watch-only、shadow-only 语义分开。
2. 把 `preferred_entry_mode`、次日开盘冲击、盘中确认空间引入主执行池筛选。
3. 只让少数满足主执行 contract 的样本进入 Pool D。

通过条件：

1. Pool D 的正收益率明显高于 Pool C。
2. Pool D 的 `T+2 >= 5%` 命中率开始可持续上升。

### Phase 4：再去追 80% / 5% 目标

这一阶段必须明确：

1. `80%` 胜率与 `5%` 收益目标，只能在 Pool D 上追，不应要求整个 BTST 候选池满足。
2. 必须加样本量和独立窗口约束。

建议最低治理门槛：

1. 至少有两个独立窗口。
2. 至少有一组 closed-cycle 样本量达到可审阅规模。
3. 不允许单票神话驱动默认升级。

---

## 9. 实施时优先看哪些指标

### 9.1 召回指标

必须新增并固定观察：

1. `result_truth_pool_count`
2. `tradeable_opportunity_pool_count`
3. `system_recall_count`
4. `selected_or_near_miss_count`
5. `tradeable_pool_capture_rate`
6. `tradeable_pool_selected_or_near_miss_rate`

### 9.2 机会质量指标

必须继续沿用：

1. `next_high_hit_rate@2%`
2. `next_high_hit_rate@5%`
3. `next_close_positive_rate`
4. `t_plus_2_close_positive_rate`
5. `t_plus_2_return_hit_rate@5%`

### 9.3 失败簇指标

必须新加：

1. `first_kill_switch_counts`
2. `first_kill_switch_strict_goal_case_counts`
3. `candidate_source_false_negative_counts`
4. `industry_false_negative_counts`
5. `strict_goal_case_false_negative_counts`

### 9.4 治理指标

必须保持：

1. `changed_non_target_case_count`
2. `distinct_window_count`
3. `spillover_count`
4. `same_rule_peer_count`

---

## 10. 未来修改方向的明确排序

下面这份排序，是本轮实施时应该严格遵守的优先级。

### 第一优先级

1. 建立 Pool A / Pool B 外部真值视角。
2. 形成原因瀑布，明确第一阻断点。
3. 固化 strict goal false negative 榜单。

### 第二优先级

1. 沿 `short_trade_boundary_score_fail` 做 score frontier 修复。
2. 针对少量高价值个案做 candidate entry selective release。

### 第三优先级

1. profitability 条件软化。
2. structural conflict 单票 / 单簇治理。

### 第四优先级

1. 把开盘消化、盘中确认、结构空间、板块共振、催化兑现节奏纳入 `entry-quality factor pack`。
2. 这部分只服务于 Pool D 的最终执行排序，不回写成 broad admission 放行规则。

---

## 11. 这轮不该做什么

为了避免再次走偏，本方案明确禁止以下动作：

1. 不加区分地把所有涨停股、炸板股、极端高开股都当成“必须留下的正确样本”。
2. 直接全局放松 profitability 或 structural conflict。
3. 在没有外部真值池的前提下，只盯 selected 样本做调参。
4. 同时联动 admission、threshold、penalty、execution 四条线。
5. 用单一窗口、单一 ticker、单一行业的成功故事推动默认升级。
6. 把 `T+2 close` 代理收益写成“系统已经验证真实可执行收益”。

---

## 12. 为什么这套方案最适合当前仓库

因为当前仓库已经具备了大部分必要基础设施，真正缺的是统一协议，而不是从零重搭系统。

仓库里已经有：

1. `selection_snapshot.json`、`selection_target_replay_input.json`、`daily_events.jsonl` 这些分层 artifact。
2. `false_negative`、`near_miss`、`blocked`、`selected` 的现成标签语义。
3. `BTST micro-window regression`、`objective monitor`、`blocker analysis`、`boundary filtered candidate review` 这些诊断工具。

因此，最快的路径不是另起炉灶，而是：

1. 新增一个从全市场结果真值池反推的脚本。
2. 把现有诊断脚本串起来。
3. 用统一口径把召回、排序、执行分开。

这也是当前能最快帮助系统靠近目标的方案。

---

## 13. 一句话版实施建议

先把 3 月所有“真正给过空间、且具有交易可达性”的票找出来，形成可交易机会池；再逐票标出它们死在系统的哪一层，优先修复最大的稳定失败簇；等召回率上来之后，再把高召回池压缩成窄的主执行池，去追 `80%` 胜率与 `5%` 收益目标。